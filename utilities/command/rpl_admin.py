#
# Copyright (c) 2010, 2013, Oracle and/or its affiliates. All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA
#

"""
This file contains the replication administration tools for managine a
simple master-to-slaves topology.
"""

import logging
import os
import sys
import time

from datetime import datetime, timedelta

from mysql.utilities.exception import UtilRplError
from mysql.utilities.common.ip_parser import hostname_is_ip
from mysql.utilities.common.messages import ERROR_SAME_MASTER
from mysql.utilities.common.tools import ping_host, execute_script
from mysql.utilities.common.format import print_list
from mysql.utilities.common.topology import Topology
from mysql.utilities.command.failover_console import FailoverConsole
from mysql.utilities.command.failover_daemon import FailoverDaemon

_VALID_COMMANDS_TEXT = """
Available Commands:

  elect       - perform best slave election and report best slave
  failover    - conduct failover from master to best slave
  gtid        - show status of global transaction id variables
                also displays uuids for all servers
  health      - display the replication health
  reset       - stop and reset all slaves
  start       - start all slaves
  stop        - stop all slaves
  switchover  - perform slave promotion

  Note:
        elect, gtid and health require --master and either
        --slaves or --discover-slaves-login;

        failover requires --slaves;

        switchover requires --master, --new-master and either
        --slaves or --discover-slaves-login;

        start, stop and reset require --slaves (and --master is optional)

"""

_VALID_COMMANDS = ["elect", "failover", "gtid", "health", "reset", "start",
                   "stop", "switchover"]
_SLAVE_COMMANDS = ["reset", "start", "stop"]
_MASTER_COLS = ["Host", "Port", "Binary Log File", "Position"]
_SLAVE_COLS = ["Host", "Port", "Master Log File", "Position", "Seconds Behind"]
_GTID_COLS = ["host", "port", "role", "gtid"]

_FAILOVER_ERROR = "%sCheck server for errors and run the mysqlrpladmin " + \
                  "utility to perform manual failover."
_FAILOVER_ERRNO = 911

_DATE_FORMAT = '%Y-%m-%d %H:%M:%S %p'
_DATE_LEN = 22

_HOST_IP_WARNING = "You may be mixing host names and IP " + \
                   "addresses. This may result in negative status " + \
                   "reporting if your DNS services do not support " + \
                   "reverse name lookup."

_ERRANT_TNX_ERROR = "Errant transaction(s) found on slave(s)."

_GTID_ON_REQ = "Slave election requires GTID_MODE=ON for all servers."

WARNING_SLEEP_TIME = 10

def get_valid_rpl_command_text():
    """Provide list of valid command descriptions to caller.
    """
    return _VALID_COMMANDS_TEXT


def get_valid_rpl_commands():
    """Provide list of valid commands to caller.
    """
    return _VALID_COMMANDS


def purge_log(filename, age):
    """Purge old log entries

    This method deletes rows from the log file older than the age specified
    in days.

    filename[in]       filename of log fil
    age[in]            age in days

    Returns bool - True = success, Fail = error reading/writing log file
    """
    if not os.path.exists(filename):
        print "NOTE: Log file '%s' does not exist. Will be created." % filename
        return True

    # Read a row, check age. If > today + age, delete row.
    # Ignore user markups and other miscellaneous entries.
    try:
        log = open(filename, "r")
        log_entries = log.readlines()
        log.close()
        threshold = datetime.now() - timedelta(days=age)
        start = 0
        for row in log_entries:
            # Check age here
            try:
                row_time = time.strptime(row[0:_DATE_LEN], _DATE_FORMAT)
                row_age = datetime(*row_time[:6])
                if row_age < threshold:
                    start += 1
                elif start == 0:
                    return True
                else:
                    break
            except:
                start += 1    # Remove invalid formatted lines
        log = open(filename, "w")
        log.writelines(log_entries[start:])
        log.close()
    except:
        return False
    return True


class RplCommands(object):
    """Replication commands.

    This class supports the following replication commands.

    elect       - perform best slave election and report best slave
    failover    - conduct failover from master to best slave as specified
                  by the user. This option performs best slave election.
    gtid        - show status of global transaction id variables
    health      - display the replication health
    reset       - stop and reset all slaves
    start       - start all slaves
    stop        - stop all slaves
    switchover  - perform slave promotion as specified by the user to a
                  specific slave. Requires --master and the --candidate
                  options.
    """

    def __init__(self, master_vals, slave_vals, options,
                 skip_conn_err=True):
        """Constructor

        master_vals[in]    master server connection dictionary
        slave_vals[in]     list of slave server connection dictionaries
        options[in]        options dictionary
        skip_conn_err[in]  if True, do not fail on connection failure
                           Default = True
        """
        # A sys.stdout copy, that can be used later to turn on/off stdout
        self.stdout_copy = sys.stdout
        self.stdout_devnull = open(os.devnull, "w")

        # Disable stdout when running --daemon with start, stop or restart
        daemon = options.get("daemon")
        if daemon:
            if daemon in ("start", "nodetach"):
                print("Starting failover daemon...")
            elif daemon == "stop":
                print("Stopping failover daemon...")
            else:
                print("Restarting failover daemon...")
            # Disable stdout if daemon not nodetach
            if daemon != "nodetach":
                sys.stdout = self.stdout_devnull

        self.master = None
        self.master_vals = master_vals
        self.options = options
        self.quiet = self.options.get("quiet", False)
        self.logging = self.options.get("logging", False)
        self.candidates = self.options.get("candidates", None)
        self.verbose = self.options.get("verbose", None)
        self.rpl_user = self.options.get("rpl_user", None)

        try:
            self.topology = Topology(master_vals, slave_vals, self.options,
                                     skip_conn_err)
        except Exception as err:
            if daemon and daemon != "nodetach":
                # Turn on sys.stdout
                sys.stdout = self.stdout_copy
            raise UtilRplError(str(err))

    def _report(self, message, level=logging.INFO, print_msg=True):
        """Log message if logging is on

        This method will log the message presented if the log is turned on.
        Specifically, if options['log_file'] is not None. It will also
        print the message to stdout.

        message[in]    message to be printed
        level[in]      level of message to log. Default = INFO
        print_msg[in]  if True, print the message to stdout. Default = True
        """
        # First, print the message.
        if print_msg and not self.quiet:
            print message
        # Now log message if logging turned on
        if self.logging:
            logging.log(int(level), message.strip("#").strip(' '))

    def _show_health(self):
        """Run a command on a list of slaves.

        This method will display the replication health of the topology. This
        includes the following for each server.

          - host       : host name
          - port       : connection port
          - role       : "MASTER" or "SLAVE"
          - state      : UP = connected, WARN = cannot connect but can ping,
                         DOWN = cannot connect nor ping
          - gtid       : ON = gtid supported and turned on, OFF = supported
                         but not enabled, NO = not supported
          - rpl_health : (master) binlog enabled,
                         (slave) IO tread is running, SQL thread is running,
                         no errors, slave delay < max_delay,
                         read log pos + max_position < master's log position
                         Note: Will show 'ERROR' if there are multiple
                         errors encountered otherwise will display the
                         health check that failed.

        If verbosity is set, it will show the following additional information.

          (master)
            - server version, binary log file, position

          (slaves)
            - server version, master's binary log file, master's log position,
              IO_Thread, SQL_Thread, Secs_Behind, Remaining_Delay,
              IO_Error_Num, IO_Error
        """
        fmt = self.options.get("format", "grid")
        quiet = self.options.get("quiet", False)

        cols, rows = self.topology.get_health()

        if not quiet:
            print "#"
            print "# Replication Topology Health:"

        # Print health report
        print_list(sys.stdout, fmt, cols, rows)

        return

    def _show_gtid_data(self):
        """Display the GTID lists from the servers.

        This method displays the three GTID lists for all of the servers. Each
        server is listed with its entries in each list. If a list has no
        entries, that list is not printed.
        """
        if not self.topology.gtid_enabled():
            self._report("# WARNING: GTIDs are not supported on this "
                         "topology.", logging.WARN)
            return

        fmt = self.options.get("format", "grid")

        # Get UUIDs
        uuids = self.topology.get_server_uuids()
        if len(uuids):
            print "#"
            print "# UUIDS for all servers:"
            print_list(sys.stdout, fmt, ['host', 'port', 'role', 'uuid'],
                       uuids)

        # Get GTID lists
        executed, purged, owned = self.topology.get_gtid_data()
        if len(executed):
            print "#"
            print "# Transactions executed on the server:"
            print_list(sys.stdout, fmt, _GTID_COLS, executed)
        if len(purged):
            print "#"
            print "# Transactions purged from the server:"
            print_list(sys.stdout, fmt, _GTID_COLS, purged)
        if len(owned):
            print "#"
            print "# Transactions owned by another server:"
            print_list(sys.stdout, fmt, _GTID_COLS, owned)

    def _check_host_references(self):
        """Check to see if using all host or all IP addresses

        Returns bool - True = all references are consistent
        """

        uses_ip = hostname_is_ip(self.topology.master.host)
        for slave_dict in self.topology.slaves:
            slave = slave_dict['instance']
            if slave is not None:
                host_port = slave.get_master_host_port()
                host = None
                if host_port:
                    host = host_port[0]
                if (not host or uses_ip != hostname_is_ip(slave.host) or
                   uses_ip != hostname_is_ip(host)):
                    return False
        return True

    def _switchover(self):
        """Perform switchover from master to candidate slave

        This method switches the role of master to a candidate slave. The
        candidate is specified via the --candidate option.

        Returns bool - True = no errors, False = errors reported.
        """
        # Check new master is not actual master - need valid candidate
        candidate = self.options.get("new_master", None)
        if (self.topology.master.is_alias(candidate['host']) and
           self.master_vals['port'] == candidate['port']):
            err_msg = ERROR_SAME_MASTER.format(candidate['host'],
                                               candidate['port'],
                                               self.master_vals['host'],
                                               self.master_vals['port'])
            self._report(err_msg, logging.WARN)
            self._report(err_msg, logging.CRITICAL)
            raise UtilRplError(err_msg)

        # Check for --master-info-repository=TABLE if rpl_user is None
        if not self._check_master_info_type():
            return False

        # Check for mixing IP and hostnames
        if not self._check_host_references():
            print "# WARNING: %s" % _HOST_IP_WARNING
            self._report(_HOST_IP_WARNING, logging.WARN, False)

        # Check prerequisites
        if candidate is None:
            msg = "No candidate specified."
            self._report(msg, logging.CRITICAL)
            raise UtilRplError(msg)

        self._report(" ".join(["# Performing switchover from master at",
                     "%s:%s" % (self.master_vals['host'],
                                self.master_vals['port']),
                               "to slave at %s:%s." %
                     (candidate['host'], candidate['port'])]))
        if not self.topology.switchover(candidate):
            self._report("# Errors found. Switchover aborted.", logging.ERROR)
            return False

        return True

    def _elect_slave(self):
        """Perform best slave election

        This method determines which slave is the best candidate for
        GTID-enabled failover. If called for a non-GTID topology, a warning
        is issued.
        """
        if not self.topology.gtid_enabled():
            print("# WARNING: {0}".format(_GTID_ON_REQ))
            self._report(_GTID_ON_REQ, logging.WARN, False)
            return

        # Check for mixing IP and hostnames
        if not self._check_host_references():
            print "# WARNING: %s" % _HOST_IP_WARNING
            self._report(_HOST_IP_WARNING, logging.WARN, False)

        candidates = self.options.get("candidates", None)
        if candidates is None or len(candidates) == 0:
            self._report("# Electing candidate slave from known slaves.")
        else:
            self._report("# Electing candidate slave from candidate list "
                         "then slaves list.")
        best_slave = self.topology.find_best_slave(candidates)
        if best_slave is None:
            self._report("ERROR: No slave found that meets eligilibility "
                         "requirements.", logging.ERROR)
            return

        self._report("# Best slave found is located on %s:%s." %
                     (best_slave['host'], best_slave['port']))

    def _failover(self, strict=False, options=None):
        """Perform failover

        This method executes GTID-enabled failover. If called for a non-GTID
        topology, a warning is issued.

        strict[in]     if True, use only the candidate list for slave
                       election and fail if no candidates are viable.
                       Default = False
        options[in]    options dictionary.

        Returns bool - True = failover succeeded, False = errors found
        """
        if options is None:
            options = {}
        srv_list = self.topology.get_servers_with_gtid_not_on()
        if srv_list:
            print("# ERROR: {0}".format(_GTID_ON_REQ))
            self._report(_GTID_ON_REQ, logging.ERROR, False)
            for srv in srv_list:
                msg = "#  - GTID_MODE={0} on {1}:{2}".format(srv[2], srv[0],
                                                             srv[1])
                self._report(msg, logging.ERROR)

            self._report(_GTID_ON_REQ, logging.CRITICAL, False)
            raise UtilRplError(_GTID_ON_REQ)

        # Check for --master-info-repository=TABLE if rpl_user is None
        if not self._check_master_info_type():
            return False

        # Check existence of errant transactions on slaves
        errant_tnx = self.topology.find_errant_transactions()
        if errant_tnx:
            force = options.get('force')
            print("# ERROR: {0}".format(_ERRANT_TNX_ERROR))
            self._report(_ERRANT_TNX_ERROR, logging.ERROR, False)
            for host, port, tnx_set in errant_tnx:
                errant_msg = (" - For slave '{0}@{1}': "
                              "{2}".format(host, port, ", ".join(tnx_set)))
                print("# {0}".format(errant_msg))
                self._report(errant_msg, logging.ERROR, False)
            # Raise an exception (to stop) if tolerant mode is OFF
            if not force:
                raise UtilRplError("%s Note: If you want to ignore this issue,"
                                   " although not advised, please use the "
                                   "utility with the --force option."
                                   % _ERRANT_TNX_ERROR)

        self._report("# Performing failover.")
        if not self.topology.failover(self.candidates, strict,
                                      stop_on_error=True):
            self._report("# Errors found.", logging.ERROR)
            return False
        return True

    def _check_master_info_type(self, halt=True):
        """Check for master information set to TABLE if rpl_user not provided

        halt[in]       if True, raise error on failure. Default is True

        Returns bool - True if rpl_user is specified or False if rpl_user not
                       specified and at least one slave does not have
                       --master-info-repository=TABLE.
        """
        error = "You must specify either the --rpl-user or set all slaves " + \
                "to use --master-info-repository=TABLE."
        # Check for --master-info-repository=TABLE if rpl_user is None
        if self.rpl_user is None:
            if not self.topology.check_master_info_type("TABLE"):
                if halt:
                    raise UtilRplError(error)
                self._report(error, logging.ERROR)
                return False
        return True

    def check_host_references(self):
        """Public method to access self.check_host_references()
        """
        return self._check_host_references()

    def execute_command(self, command, options=None):
        """Execute a replication admin command

        This method executes one of the valid replication administration
        commands as described above.

        command[in]        command to execute
        options[in]        options dictionary.

        Returns bool - True = success, raise error on failure
        """
        if options is None:
            options = {}
        # Raise error if command is not valid
        if not command in _VALID_COMMANDS:
            msg = "'%s' is not a valid command." % command
            self._report(msg, logging.CRITICAL)
            raise UtilRplError(msg)

        # Check privileges
        self._report("# Checking privileges.")
        full_check = command in ['failover', 'elect', 'switchover']
        errors = self.topology.check_privileges(full_check)
        if len(errors):
            msg = "User %s on %s does not have sufficient privileges to " + \
                  "execute the %s command."
            for error in errors:
                self._report(msg % (error[0], error[1], command),
                             logging.CRITICAL)
            raise UtilRplError("Not enough privileges to execute command.")

        self._report("Executing %s command..." % command, logging.INFO, False)

        # Execute the command
        if command in _SLAVE_COMMANDS:
            if command == 'reset':
                self.topology.run_cmd_on_slaves('stop')
            self.topology.run_cmd_on_slaves(command)
        elif command in 'gtid':
            self._show_gtid_data()
        elif command == 'health':
            self._show_health()
        elif command == 'switchover':
            self._switchover()
        elif command == 'elect':
            self._elect_slave()
        elif command == 'failover':
            self._failover(options=options)
        else:
            msg = "Command '%s' is not implemented." % command
            self._report(msg, logging.CRITICAL)
            raise UtilRplError(msg)

        if command in ['switchover', 'failover'] and \
           not self.options.get("no_health", False):
            self._show_health()

        self._report("# ...done.")

        return True

    def auto_failover(self, interval):
        """Automatic failover

        Wrapper class for running automatic failover. See
        run_automatic_failover for details on implementation.

        This method ensures the registration/deregistration occurs
        regardless of exception or errors.

        interval[in]   time in seconds to wait to check status of servers

        Returns bool - True = success, raises exception on error
        """
        failover_mode = self.options.get("failover_mode", "auto")
        force = self.options.get("force", False)

        # Initialize a console
        console = FailoverConsole(self.topology.master,
                                  self.topology.get_health,
                                  self.topology.get_gtid_data,
                                  self.topology.get_server_uuids,
                                  self.options)

        # Unregister existing instances from slaves
        self._report("Unregistering existing instances from slaves.",
                     logging.INFO, False)
        console.unregister_slaves(self.topology)

        # Register instance
        self._report("Registering instance on master.", logging.INFO, False)
        old_mode = failover_mode
        failover_mode = console.register_instance(force)
        if failover_mode != old_mode:
            self._report("Multiple instances of failover console found for "
                         "master %s:%s." % (self.topology.master.host,
                                            self.topology.master.port),
                         logging.WARN)
            print "If this is an error, restart the console with --force. "
            print "Failover mode changed to 'FAIL' for this instance. "
            print "Console will start in 10 seconds.",
            sys.stdout.flush()
            i = 0
            while i < 9:
                time.sleep(1)
                sys.stdout.write('.')
                sys.stdout.flush()
                i += 1
            print "starting Console."
            time.sleep(1)

        try:
            res = self.run_auto_failover(console, interval, failover_mode)
        except:
            raise
        finally:
            try:
                # Unregister instance
                self._report("Unregistering instance on master.", logging.INFO,
                             False)
                console.register_instance(True, False)
                self._report("Failover console stopped.", logging.INFO, False)
            except:
                pass

        return res

    def auto_failover_as_daemon(self):
        """Automatic failover

        Wrapper class for running automatic failover as daemon.

        This method ensures the registration/deregistration occurs
        regardless of exception or errors.

        Returns bool - True = success, raises exception on error
        """
        # Initialize failover daemon
        failover_daemon = FailoverDaemon(self)
        res = None

        try:
            action = self.options.get("daemon")
            if action == "start":
                res = failover_daemon.start()
            elif action == "stop":
                res = failover_daemon.stop()
            elif action == "restart":
                res = failover_daemon.restart()
            else:
                # Start failover deamon in foreground
                res = failover_daemon.start(detach_process=False)
        except:
            try:
                # Unregister instance
                self._report("Unregistering instance on master.", logging.INFO,
                             False)
                failover_daemon.register_instance(True, False)
                self._report("Failover daemon stopped.", logging.INFO, False)
            except:
                pass

        return res

    def run_auto_failover(self, console, interval, failover_mode="auto"):
        """Run automatic failover

        This method implements the automatic failover facility. It uses the
        FailoverConsole class from the failover_console.py to implement all
        user interface commands and uses the existing failover() method of
        this class to conduct failover.

        When the master goes down, the method can perform one of three actions:

        1) failover to list of candidates first then slaves
        2) failover to list of candidates only
        3) fail

        console[in]    instance of the failover console class
        interval[in]   time in seconds to wait to check status of servers

        Returns bool - True = success, raises exception on error
        """
        pingtime = self.options.get("pingtime", 3)
        exec_fail = self.options.get("exec_fail", None)
        post_fail = self.options.get("post_fail", None)
        pedantic = self.options.get('pedantic', False)

        # Only works for GTID_MODE=ON
        if not self.topology.gtid_enabled():
            msg = "Topology must support global transaction ids " + \
                  "and have GTID_MODE=ON."
            self._report(msg, logging.CRITICAL)
            raise UtilRplError(msg)

        # Check privileges
        self._report("# Checking privileges.")
        errors = self.topology.check_privileges(failover_mode != 'fail')
        if len(errors):
            for error in errors:
                msg = ("User {0} on {1}@{2} does not have sufficient "
                       "privileges to execute the {3} command "
                       "(required: {4}).").format(error[0], error[1], error[2],
                                                  'failover', error[3])
                print("# ERROR: {0}".format(msg))
                self._report(msg, logging.CRITICAL, False)
            raise UtilRplError("Not enough privileges to execute command.")

        # Require --master-info-repository=TABLE for all slaves
        if not self.topology.check_master_info_type("TABLE"):
            msg = "Failover requires --master-info-repository=TABLE for " + \
                  "all slaves."
            self._report(msg, logging.ERROR, False)
            raise UtilRplError(msg)

        # Check for mixing IP and hostnames
        if not self._check_host_references():
            print "# WARNING: %s" % _HOST_IP_WARNING
            self._report(_HOST_IP_WARNING, logging.WARN, False)
            print("#\n# Failover console will start in {0} seconds.".format(
                WARNING_SLEEP_TIME))
            time.sleep(WARNING_SLEEP_TIME)

        # Test failover script. If it doesn't exist, fail.
        no_exec_fail_msg = "Failover check script cannot be found. Please " + \
                           "check the path and filename for accuracy and " + \
                           "restart the failover console."
        if exec_fail is not None and not os.path.exists(exec_fail):
            self._report(no_exec_fail_msg, logging.CRITICAL, False)
            raise UtilRplError(no_exec_fail_msg)

        # Check existence of errant transactions on slaves
        errant_tnx = self.topology.find_errant_transactions()
        if errant_tnx:
            print("# WARNING: {0}".format(_ERRANT_TNX_ERROR))
            self._report(_ERRANT_TNX_ERROR, logging.WARN, False)
            for host, port, tnx_set in errant_tnx:
                errant_msg = (" - For slave '{0}@{1}': "
                              "{2}".format(host, port, ", ".join(tnx_set)))
                print("# {0}".format(errant_msg))
                self._report(errant_msg, logging.WARN, False)
            # Raise an exception (to stop) if pedantic mode is ON
            if pedantic:
                raise UtilRplError("{0} Note: If you want to ignore this "
                                   "issue, please do not use the --pedantic "
                                   "option.".format(_ERRANT_TNX_ERROR))

        self._report("Failover console started.", logging.INFO, False)
        self._report("Failover mode = %s." % failover_mode, logging.INFO,
                     False)

        # Main loop - loop and fire on interval.
        done = False
        first_pass = True
        failover = False
        while not done:
            # Use try block in case master class has gone away.
            try:
                old_host = self.master.host
                old_port = self.master.port
            except:
                old_host = "UNKNOWN"
                old_port = "UNKNOWN"

            # If a failover script is provided, check it else check master
            # using connectivity checks.
            if exec_fail is not None:
                # Execute failover check script
                if not os.path.exists(exec_fail):
                    self._report(no_exec_fail_msg, logging.CRITICAL, False)
                    raise UtilRplError(no_exec_fail_msg)
                else:
                    self._report("# Spawning external script for failover "
                                 "checking.")
                    res = execute_script(exec_fail, None,
                                         [old_host, old_port], self.verbose)
                    if res == 0:
                        self._report("# Failover check script completed Ok. "
                                     "Failover averted.")
                    else:
                        self._report("# Failover check script failed. "
                                     "Failover initiated", logging.WARN)
                        failover = True
            else:
                # Check the master. If not alive, wait for pingtime seconds
                # and try again.
                if self.topology.master is not None and \
                   not self.topology.master.is_alive():
                    msg = "Master may be down. Waiting for %s seconds." % \
                          pingtime
                    self._report(msg, logging.INFO, False)
                    time.sleep(pingtime)
                    try:
                        self.topology.master.connect()
                    except:
                        pass

                # Check the master again. If no connection or lost connection,
                # try ping. This performs the timeout threshold for detecting
                # a down master. If still not alive, try to reconnect and if
                # connection fails after 3 attempts, failover.
                if self.topology.master is None or \
                   not ping_host(self.topology.master.host, pingtime) or \
                   not self.topology.master.is_alive():
                    failover = True
                    i = 0
                    while i < 3:
                        try:
                            self.topology.master.connect()
                            failover = False  # Master is now connected again
                            break
                        except:
                            pass
                        time.sleep(pingtime)
                        i += 1

                    if failover:
                        self._report("Failed to reconnect to the master after "
                                     "3 attemps.", logging.INFO)

            if failover:
                self._report("Master is confirmed to be down or unreachable.",
                             logging.CRITICAL, False)
                try:
                    self.topology.master.disconnect()
                except:
                    pass
                console.clear()
                if failover_mode == 'auto':
                    self._report("Failover starting in 'auto' mode...")
                    res = self.topology.failover(self.candidates, False)
                elif failover_mode == 'elect':
                    self._report("Failover starting in 'elect' mode...")
                    res = self.topology.failover(self.candidates, True)
                else:
                    msg = _FAILOVER_ERROR % ("Master has failed and automatic "
                                             "failover is not enabled. ")
                    self._report(msg, logging.CRITICAL, False)
                    # Execute post failover script
                    self.topology.run_script(post_fail, False,
                                             [old_host, old_port])
                    raise UtilRplError(msg, _FAILOVER_ERRNO)
                if not res:
                    msg = _FAILOVER_ERROR % ("An error was encountered "
                                             "during failover. ")
                    self._report(msg, logging.CRITICAL, False)
                    # Execute post failover script
                    self.topology.run_script(post_fail, False,
                                             [old_host, old_port])
                    raise UtilRplError(msg)
                self.master = self.topology.master
                console.master = self.master
                self.topology.remove_discovered_slaves()
                self.topology.discover_slaves()
                console.list_data = None
                print "\nFailover console will restart in 5 seconds."
                time.sleep(5)
                console.clear()
                failover = False
                # Execute post failover script
                self.topology.run_script(post_fail, False,
                                         [old_host, old_port,
                                          self.master.host, self.master.port])

                # Unregister existing instances from slaves
                self._report("Unregistering existing instances from slaves.",
                             logging.INFO, False)
                console.unregister_slaves(self.topology)

                # Register instance on the new master
                self._report("Registering instance on master.", logging.INFO,
                             False)
                failover_mode = console.register_instance()

            # discover slaves if option was specified at startup
            elif self.options.get("discover", None) is not None and \
                    (not first_pass or self.options.get("rediscover", False)):
                # Force refresh of health list if new slaves found
                if self.topology.discover_slaves():
                    console.list_data = None

            # Check existence of errant transactions on slaves
            errant_tnx = self.topology.find_errant_transactions()
            if errant_tnx:
                if pedantic:
                    print("# WARNING: {0}".format(_ERRANT_TNX_ERROR))
                    self._report(_ERRANT_TNX_ERROR, logging.WARN, False)
                    for host, port, tnx_set in errant_tnx:
                        errant_msg = (" - For slave '{0}@{1}': "
                                      "{2}".format(host, port,
                                                   ", ".join(tnx_set)))
                        print("# {0}".format(errant_msg))
                        self._report(errant_msg, logging.WARN, False)

                    # Raise an exception (to stop) if pedantic mode is ON
                    raise UtilRplError("{0} Note: If you want to ignore this "
                                       "issue, please do not use the "
                                       "--pedantic "
                                       "option.".format(_ERRANT_TNX_ERROR))
                else:
                    if self.logging:
                        warn_msg = ("{0} Check log for more "
                                    "details.".format(_ERRANT_TNX_ERROR))
                    else:
                        warn_msg = _ERRANT_TNX_ERROR
                    console.add_warning('errant_tnx', warn_msg)
                    self._report(_ERRANT_TNX_ERROR, logging.WARN, False)
                    for host, port, tnx_set in errant_tnx:
                        errant_msg = (" - For slave '{0}@{1}': "
                                      "{2}".format(host, port,
                                                   ", ".join(tnx_set)))
                        self._report(errant_msg, logging.WARN, False)
            else:
                console.del_warning('errant_tnx')

            res = console.display_console()
            if res is not None:    # None = normal timeout, keep going
                if not res:
                    return False   # Errors detected
                done = True        # User has quit
            first_pass = False

        return True
