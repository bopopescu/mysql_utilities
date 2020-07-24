#
# Copyright (c) 2013 Oracle and/or its affiliates. All rights reserved.
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
This file contains output string messages used by MySQL Utilities.
"""


PARSE_ERR_DB_PAIR = ("Cannot parse the specified database(s): '{db_pair}'. "
                     "Please verify that the database(s) are specified in "
                     "a valid format (i.e., {db1_label}[:{db2_label}]) and "
                     "that backtick quotes are properly used when required.")

PARSE_ERR_DB_PAIR_EXT = ("%s The use of backticks is required if non "
                         "alphanumeric characters are used for database "
                         "names. Parsing the specified database results "
                         "in {db1_label} = '{db1_value}' and "
                         "{db2_label} = '{db2_value}'." % PARSE_ERR_DB_PAIR)

PARSE_ERR_DB_OBJ_PAIR = ("Cannot parse the specified database objects: "
                         "'{db_obj_pair}'. Please verify that the objects "
                         "are specified in a valid format (i.e., {db1_label}"
                         "[.{obj1_label}]:{db2_label}[.{obj2_label}]) and "
                         "that backtick quotes are properly used if "
                         "required.")

PARSE_ERR_DB_OBJ_PAIR_EXT = ("%s The use of backticks is required if non "
                             "alphanumeric characters are used for identifier "
                             "names. Parsing the specified objects results "
                             "in: {db1_label} = '{db1_value}', "
                             "{obj1_label} = '{obj1_value}', "
                             "{db2_label} = '{db2_value}' and "
                             "{obj2_label} = '{obj2_value}'."
                             % PARSE_ERR_DB_OBJ_PAIR)

PARSE_ERR_DB_OBJ_MISSING_MSG = ("Incorrect object compare argument, one "
                                "specific object is missing. Please verify "
                                "that both object are correctly specified. "
                                "{detail} Format should be: "
                                "{db1_label}[.{obj1_label}]"
                                ":{db2_label}[.{obj2_label}].")

PARSE_ERR_DB_OBJ_MISSING = ("No object has been specified for "
                            "{db_no_obj_label} '{db_no_obj_value}', while "
                            "object '{only_obj_value}' was specified for "
                            "{db_obj_label} '{db_obj_value}'.")

PARSE_ERR_DB_MISSING_CMP = "No databases specified to compare."

PARSE_ERR_SPAN_KEY_SIZE_TOO_LOW = (
    "The value {s_value} specified for option --span-key-size is too small "
    "and would cause inaccurate results, please retry with a bigger value "
    "or the default value of {default}.")

PARSE_ERR_OPT_INVALID_CMD = ("Invalid {opt} option for '{cmd}'.")

PARSE_ERR_OPT_INVALID_CMD_TIP = ("%s Use {opt_tip} instead."
                                 % PARSE_ERR_OPT_INVALID_CMD)

PARSE_ERR_OPTS_REQ = "Option '{opt}' is required."

PARSE_ERR_OPTS_REQ_BY_CMD = ("'{cmd}' requires the following option(s): "
                             "{opts}.")

PARSE_ERR_SLAVE_DISCO_REQ = ("Option --discover-subordinates-login or --subordinates is "
                             "required.")

PARSE_ERR_SLAVE_DISCO_EXC = ("Options --discover-subordinates-login and --subordinates "
                             "cannot be used simultaneously.")

WARN_OPT_NOT_REQUIRED = ("WARNING: The {opt} option is not required for "
                         "'{cmd}' (option ignored).")

WARN_OPT_NOT_REQUIRED_ONLY_FOR = ("%s Only used with the {only_cmd} command."
                                  % WARN_OPT_NOT_REQUIRED)

WARN_OPT_ONLY_USED_WITH = ("# WARNING: The {opt} option is only used with "
                           "{used_with} (option ignored).")

WARN_OPT_USING_DEFAULT = ("WARNING: Using default value '{default}' for "
                          "option {opt}.")

ERROR_SAME_MASTER = ("The specified new main {n_main_host}:{n_main_port}"
                     " is the same as the "
                     "actual main {main_host}:{main_port}.")

SLAVES = "subordinates"

CANDIDATES = "candidates"

ERROR_MASTER_IN_SLAVES = ("The main {main_host}:{main_port} "
                          "and one of the specified {subordinates_candidates} "
                          "are the same {subordinate_host}:{subordinate_port}.")

SCRIPT_THRESHOLD_WARNING = ("WARNING: You have chosen to use external script "
                            "return code checking. Depending on which script "
                            "fails, this can leave the operation in an "
                            "undefined state. Please check your results "
                            "carefully if the operation aborts.")
