from PySide2.QtWidgets import *
from PySide2.QtGui import *
from PySide2.QtCore import *
from src.xASL_GUI_HelperClasses import DandD_FileExplorer2LineEdit, xASL_PushButton
from src.xASL_GUI_HelperFuncs_WidgetFuncs import set_formlay_options, robust_qmsg
from src.xASL_GUI_Dehybridizer import xASL_GUI_Dehybridizer
from src.xASL_GUI_DCM2NIFTI import *
from tdda import rexpy
from pprint import pprint
from collections import OrderedDict
from more_itertools import divide, flatten, collapse
import json
from os import chdir
from platform import system
from pathlib import Path
from typing import List, Iterator, Set
import logging
from datetime import datetime


class Importer_WorkerSignals(QObject):
    """
    Class for handling the signals sent by an ExploreASL worker
    """
    signal_send_summaries = Signal(list)  # Signal sent by worker to process the summaries of imported files
    signal_send_errors = Signal(list)  # Signal sent by worker to indicate the file where something has failed
    signal_update_progressbar = Signal()  # Signal sent by worker to indicate a completed directory
    signal_confirm_terminate = Signal()  # Signal sent by worker to indicate a termination had occurred


# noinspection PyUnresolvedReferences
class Importer_Worker(QRunnable):
    """
    Worker thread for running the import for a particular group.
    """

    def __init__(self, dcm_dirs: Iterator[Path], config: dict, use_legacy_mode: bool, name: str = None):
        self.dcm_dirs: Iterator[Path] = dcm_dirs
        self.import_config: dict = config
        self.use_legacy_mode: bool = use_legacy_mode
        super().__init__()
        self.signals = Importer_WorkerSignals()
        self.import_summaries = []
        self.failed_runs = []
        self.name = name
        self._terminated = False

        logger = logging.Logger(name=name, level=logging.DEBUG)
        self.converter = DCM2NIFTI_Converter(config=config, name=name, logger=logger, b_legacy=use_legacy_mode)
        print("Initialized Worker with args:\n")
        pprint(self.import_config)

    def run(self):
        for dicom_dir in self.dcm_dirs:
            if not self._terminated:
                success, job_description = self.converter.process_dcm_dir(dcm_dir=dicom_dir)
                if success:
                    self.import_summaries.append(self.converter.summary_data.copy())
                    self.signals.signal_update_progressbar.emit()
                else:
                    self.failed_runs.append(job_description)
                    self.signals.signal_update_progressbar.emit()

        # Cleanup handlers and such
        if not self._terminated:
            self.converter.logger.removeHandler(self.converter.handler)

            self.signals.signal_send_summaries.emit(self.import_summaries)
            if len(self.failed_runs) > 0:
                self.signals.signal_send_errors.emit(self.failed_runs)

        else:
            self.signals.signal_confirm_terminate.emit()

    @Slot()
    def slot_stop_import(self):
        print(f"{self.name} received a termination signal! Terminating at the next available DICOM dir.")
        self._terminated = True


# noinspection PyCallingNonCallable
class xASL_GUI_Importer(QMainWindow):
    signal_stop_import = Signal()

    def __init__(self, parent_win=None):
        # Parent window is fed into the constructor to allow for communication with parent window devices
        super().__init__(parent=parent_win)
        self.config = parent_win.config
        with open(Path(self.config["ProjectDir"]) / "JSON_LOGIC" / "ErrorsListing.json") as import_err_reader:
            self.import_errs = json.load(import_err_reader)
        with open(Path(self.config["ProjectDir"]) / "JSON_LOGIC" / "ToolTips.json") as import_tooltips_reader:
            self.import_tips = json.load(import_tooltips_reader)["Importer"]
        del import_err_reader, import_tooltips_reader

        # Misc and Default Attributes
        self.labfont = QFont()
        self.labfont.setPointSize(16)
        self.lefont = QFont()
        self.lefont.setPointSize(12)
        self.rawdir = ''
        self.delim = "\\" if system() == "Windows" else "/"
        self.subject_regex = None
        self.visit_regex = None
        self.run_regex = None
        self.scan_regex = None
        self.run_aliases = OrderedDict()
        self.scan_aliases = dict.fromkeys(["ASL4D", "T1", "T2" "M0", "FLAIR"])
        self.cmb_runaliases_dict = {}
        self.threadpool = QThreadPool()
        self.import_summaries = []
        self.failed_runs = []
        self.import_workers = []

        # Window Size and initial visual setup
        self.setWindowTitle("ExploreASL - DICOM to NIFTI Import")
        self.cw = QWidget(self)
        self.setCentralWidget(self.cw)
        self.mainlay = QVBoxLayout(self.cw)
        self.mainlay.setContentsMargins(0, 5, 0, 0)
        self.resize(self.config["ScreenSize"][0] // 3.5, self.height())  # Hack, window a bit too wide without this

        # The central tab widget and its setup
        self.central_tab_widget = QTabWidget()
        self.cont_import = QWidget()
        self.vlay_import = QVBoxLayout(self.cont_import)
        self.cont_dehybridizer = QWidget()
        self.vlay_dehybridizer = QVBoxLayout(self.cont_dehybridizer)
        self.vlay_dehybridizer.setContentsMargins(0, 0, 0, 0)
        self.central_tab_widget.addTab(self.cont_import, "Importer")
        self.central_tab_widget.addTab(self.cont_dehybridizer, "Expand Directories")
        self.mainlay.addWidget(self.central_tab_widget)

        # The importer UI setup
        self.mainsplit = QSplitter(Qt.Vertical)
        handle_path = str(Path(self.config["ProjectDir"]) / "media" / "3_dots_horizontal.svg")
        if system() == "Windows":
            handle_path = handle_path.replace("\\", "/")
        handle_style = 'QSplitter::handle {image: url(' + handle_path + ');}'
        self.mainsplit.setStyleSheet(handle_style)
        self.mainsplit.setHandleWidth(20)

        self.Setup_UI_UserSpecifyDirStuct()
        self.Setup_UI_UserSpecifyScanAliases()
        self.Setup_UI_UserSpecifyRunAliases()

        # Img_vars
        icon_import = QIcon(str(Path(self.config["ProjectDir"]) / "media" / "import_win10_64x64.png"))
        icon_terminate = QIcon(str(Path(self.config["ProjectDir"]) / "media" / "stop_processing.png"))

        # Bottom split: the progressbar and Run/Stop buttons
        self.cont_runbtns = QWidget()
        self.mainsplit.addWidget(self.cont_runbtns)
        self.vlay_runbtns = QVBoxLayout(self.cont_runbtns)
        self.progbar_import = QProgressBar(orientation=Qt.Horizontal, minimum=0, value=0, maximum=1, textVisible=True)
        if system() == "Darwin":
            self.progbar_import.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_run_importer = xASL_PushButton(text="Convert DICOM to NIFTI", func=self.run_importer,
                                                font=self.labfont, fixed_height=50, enabled=False, icon=icon_import,
                                                icon_size=QSize(40, 40))
        self.btn_terminate_importer = xASL_PushButton(enabled=False, icon=icon_terminate, icon_size=QSize(40, 40),
                                                      func=self.signal_stop_import.emit)
        self.vlay_runbtns.addStretch(1)
        for widget in [self.progbar_import, self.btn_run_importer, self.btn_terminate_importer]:
            self.vlay_runbtns.addWidget(widget)
        self.vlay_import.addWidget(self.mainsplit)

        # The dehybridizer UI setup
        self.dehybridizer = xASL_GUI_Dehybridizer(self)
        self.vlay_dehybridizer.addWidget(self.dehybridizer)

        # Additional MacOS options
        if system() == "Darwin":
            set_formlay_options(self.formlay_rootdir, vertical_spacing=3)
            set_formlay_options(self.formlay_scanaliases)
            set_formlay_options(self.formlay_runaliases)
            self.vlay_dirstruct.setSpacing(5)

    def Setup_UI_UserSpecifyDirStuct(self):
        self.grp_dirstruct = QGroupBox(title="Specify Directory Structure")
        self.vlay_dirstruct = QVBoxLayout(self.grp_dirstruct)

        # First specify the root directory
        self.formlay_rootdir = QFormLayout()
        self.hlay_rootdir = QHBoxLayout()
        self.le_rootdir = DandD_FileExplorer2LineEdit(acceptable_path_type="Directory")
        self.le_rootdir.setPlaceholderText("Drag & drop the root directory of your DICOM folder structure")
        self.le_rootdir.setToolTip(self.import_tips["le_rootdir"])
        self.le_rootdir.setReadOnly(True)
        self.le_rootdir.textChanged.connect(self.set_rootdir_variable)
        self.le_rootdir.textChanged.connect(self.clear_widgets)
        self.le_rootdir.textChanged.connect(self.is_ready_import)
        self.btn_setrootdir = QPushButton("...", clicked=self.set_import_root_directory)
        self.hlay_rootdir.addWidget(self.le_rootdir)
        self.hlay_rootdir.addWidget(self.btn_setrootdir)
        self.chk_uselegacy = QCheckBox(checked=True)
        self.chk_uselegacy.setToolTip(self.import_tips["chk_uselegacy"])
        self.formlay_rootdir.addRow("Source Root Directory", self.hlay_rootdir)
        self.formlay_rootdir.addRow("Use Legacy Import", self.chk_uselegacy)

        # Next specify the QLabels that can be dragged to have their text copied elsewhere
        self.hlay_placeholders = QHBoxLayout()
        self.lab_holdersub = DraggableLabel("Subject", self.grp_dirstruct)
        self.lab_holdervisit = DraggableLabel("Visit", self.grp_dirstruct)
        self.lab_holderrun = DraggableLabel("Run", self.grp_dirstruct)
        self.lab_holderscan = DraggableLabel("Scan", self.grp_dirstruct)
        self.lab_holderdummy = DraggableLabel("Dummy", self.grp_dirstruct)
        for lab, tip in zip([self.lab_holdersub, self.lab_holdervisit, self.lab_holderrun, self.lab_holderscan,
                             self.lab_holderdummy],
                            [self.import_tips["lab_holdersub"], self.import_tips["lab_holdervisit"],
                             self.import_tips["lab_holderrun"], self.import_tips["lab_holderscan"],
                             self.import_tips["lab_holderdummy"]]):
            lab.setToolTip(tip)
            self.hlay_placeholders.addWidget(lab)

        # Next specify the QLineEdits that will be receiving the dragged text
        self.hlay_receivers = QHBoxLayout()
        self.lab_rootlabel = QLabel(text="root")
        self.lab_rootlabel.setFont(self.labfont)
        self.levels = {}
        for idx, (level, func) in enumerate(zip(["Level1", "Level2", "Level3", "Level4", "Level5", "Level6", "Level7"],
                                                [self.get_nth_level_dirs] * 7)):
            le = DandD_Label2LineEdit(self, self.grp_dirstruct, idx)
            le.modified_text.connect(self.get_nth_level_dirs)
            le.textChanged.connect(self.update_sibling_awareness)
            le.textChanged.connect(self.is_ready_import)
            le.setToolTip(f"This field accepts a drag & droppable label describing the information found at\n"
                          f"a directory depth of {idx + 1} after the root folder")
            self.levels[level] = le

        self.hlay_receivers.addWidget(self.lab_rootlabel)
        lab_sep = QLabel(text=self.delim)
        lab_sep.setFont(self.labfont)
        self.hlay_receivers.addWidget(lab_sep)
        for ii, level in enumerate(self.levels.values()):
            level.setFont(self.lefont)
            self.hlay_receivers.addWidget(level)
            if ii < 6:
                lab_sep = QLabel(text=self.delim)
                lab_sep.setFont(self.labfont)
                self.hlay_receivers.addWidget(lab_sep)

        # Include the button that will clear the current structure for convenience
        self.btn_clear_receivers = QPushButton("Clear the fields", self.grp_dirstruct, clicked=self.clear_receivers)

        # Organize layouts
        self.vlay_dirstruct.addLayout(self.formlay_rootdir)
        self.vlay_dirstruct.addLayout(self.hlay_placeholders)
        self.vlay_dirstruct.addLayout(self.hlay_receivers)
        self.vlay_dirstruct.addWidget(self.btn_clear_receivers)

        self.mainsplit.addWidget(self.grp_dirstruct)

    def Setup_UI_UserSpecifyScanAliases(self):
        # Next specify the scan aliases
        self.grp_scanaliases = QGroupBox(title="Specify Scan Aliases")
        self.cmb_scanaliases_dict = dict.fromkeys(["ASL4D", "T1", "T2", "M0", "FLAIR"])
        self.formlay_scanaliases = QFormLayout(self.grp_scanaliases)
        for description, scantype in zip(["ASL scan alias", "T1 scan alias:", "T2 scan alias",
                                          "M0 scan alias:", "FLAIR scan alias:"],
                                         self.cmb_scanaliases_dict.keys()):
            cmb = QComboBox(self.grp_scanaliases)
            cmb.setToolTip("Specify the folder name that corresponds to the indicated type of scan on the left")
            cmb.addItems(["Select an alias"])
            cmb.currentTextChanged.connect(self.update_scan_aliases)
            cmb.currentTextChanged.connect(self.is_ready_import)
            self.cmb_scanaliases_dict[scantype] = cmb
            self.formlay_scanaliases.addRow(description, cmb)
            if system() == "Darwin":
                cmb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.mainsplit.addWidget(self.grp_scanaliases)

    def Setup_UI_UserSpecifyRunAliases(self):
        # Define the groupbox and its main layout
        self.grp_runaliases = QGroupBox(title="Specify Run Aliases and Ordering")
        self.vlay_runaliases = QVBoxLayout(self.grp_runaliases)
        self.vlay_runaliases.setContentsMargins(0, 0, 0, 0)
        self.scroll_runaliases = QScrollArea(self.grp_runaliases)
        self.cont_runaliases = QWidget()
        self.scroll_runaliases.setWidget(self.cont_runaliases)
        self.scroll_runaliases.setWidgetResizable(True)

        # Arrange widgets and layouts
        self.le_runaliases_dict = dict()
        self.formlay_runaliases = QFormLayout(self.cont_runaliases)
        self.vlay_runaliases.addWidget(self.scroll_runaliases)
        self.mainsplit.addWidget(self.grp_runaliases)

    # Purpose of this function is to set the directory of the root path lineedit based on the adjacent pushbutton
    @Slot()
    def set_import_root_directory(self):
        dir_path = QFileDialog.getExistingDirectory(QFileDialog(),
                                                    "Select the raw directory of your study",
                                                    self.parent().config["DefaultRootDir"],
                                                    QFileDialog.ShowDirsOnly)
        if dir_path == "":
            return
        self.le_rootdir.setText(str(Path(dir_path)))

    # Purpose of this function is to change the value of the rawdir attribute based on the current text
    @Slot()
    def set_rootdir_variable(self, path: str):
        if path == '':
            self.rawdir = ""
            return
        path = Path(path)
        if path.exists() and path.is_dir():
            self.rawdir = self.le_rootdir.text()

    def get_nth_level_dirs(self, dir_type: str, level: int):
        """
        :param dir_type: whether this is a subject, visit, run or scan
        :param level: which lineedit, in python index terms, emitted this signal
        """
        # Requirements to proceed
        if any([self.rawdir == "",
                not Path(self.rawdir).exists(),
                not Path(self.rawdir).is_dir()
                ]):
            return

        # Check if a reset is needed
        self.check_if_reset_needed()

        # If this was a clearing, the dir_type will be an empty string and the function should exit after any resetting
        # has been performed
        if dir_type == '':
            return

        try:
            delimiter = "\\" if system() == "Windows" else "/"
            glob_string = delimiter.join(["*"] * (level + 1))
            paths = [(str(direc), str(direc.name)) for direc in Path(self.rawdir).glob(glob_string)]
            directories, basenames = zip(*paths)

        except ValueError:
            robust_qmsg(self, title=self.import_errs["ImpossibleDirDepth"][0],
                        body=self.import_errs["ImpossibleDirDepth"][1])
            # Clear the appropriate lineedit that called this function after the error message
            list(self.levels.values())[level].clear()
            return

        # Do not proceed if no directories were found and clear the linedit that emitted the textChanged signal
        if len(directories) == 0:
            idx = list(self.levels.keys())[level]
            print(f"{idx=}")
            self.levels[idx].clear()
            return

        # Otherwise, make the appropriate adjustment depending on which label was dropped in
        if dir_type == "Subject":
            self.subject_regex = self.infer_regex(list(basenames))
            print(f"Subject regex: {self.subject_regex}")
            del directories, basenames

        elif dir_type == "Visit":
            self.visit_regex = self.infer_regex(list(basenames))
            print(f"Visit regex: {self.visit_regex}")
            del directories, basenames

        elif dir_type == "Run":
            self.run_regex = self.infer_regex(list(set(basenames)))
            print(f"Run regex: {self.run_regex}")
            self.reset_run_aliases(basenames=list(set(basenames)))
            del directories, basenames

        elif dir_type == "Scan":
            self.scan_regex = self.infer_regex(list(set(basenames)))
            print(f"Scan regex: {self.scan_regex}")
            self.reset_scan_alias_cmbs(basenames=sorted(set(basenames)))
            del directories, basenames

        elif dir_type == "Dummy":
            del directories, basenames
            return

        else:
            del directories, basenames
            print("Error. This should never print")
            return

    #####################################
    # SECTION - RESET AND CLEAR FUNCTIONS
    #####################################

    def clear_widgets(self):
        """
        Raw reset. Resets all important variables upon a change in the indicated raw directory text.
        """
        # Resets everything back to normal
        self.subject_regex = None
        self.visit_regex = None
        self.run_regex = None
        self.scan_regex = None
        self.clear_receivers()
        self.clear_run_alias_cmbs_and_les()
        self.reset_scan_alias_cmbs(basenames=None)
        self.run_aliases = OrderedDict()
        self.scan_aliases = dict.fromkeys(["ASL4D", "T1", "T2", "M0", "FLAIR"])

        if self.config["DeveloperMode"]:
            print("clear_widgets engaged due to a change in the indicated Raw directory")

    def check_if_reset_needed(self):
        """
        More specialized reset function. If any of the drop-enabled lineedits has their field change,
        this function will accomodate that change by resetting the variable that may have been removed
        during the drop
        """
        used_directories = [le.text() for le in self.levels.values()]
        # If subjects is not in the currently-specified structure and the regex has been already set
        if "Subject" not in used_directories and self.subject_regex is not None:
            self.subject_regex = None

        # If visits is not in the currently-specified structure and the regex has been already set
        if "Visit" not in used_directories and self.visit_regex is not None:
            self.visit_regex = None

        # If runs is not in the currently-specified structure and the regex has been already set
        if "Run" not in used_directories and self.run_regex is not None:
            self.run_regex = None
            self.run_aliases.clear()
            self.clear_run_alias_cmbs_and_les()  # This clears the runaliases dict and the widgets

        if "Scan" not in used_directories and self.scan_regex is not None:
            self.scan_regex = None
            self.scan_aliases = dict.fromkeys(["ASL4D", "T1", "T2", "M0", "FLAIR"])
            self.reset_scan_alias_cmbs(basenames=None)

    def clear_receivers(self):
        """
        Convenience function for resetting the drop-enabled lineedits
        """
        for le in self.levels.values():
            le.clear()

    def reset_scan_alias_cmbs(self, basenames=None):
        """
        Resets all comboboxes in the scans section and repopulates them with new options
        :param basenames: filepath basenames to populate the comboboxes with
        """
        if basenames is None:
            basenames = []

        # Must first disconnect the combobox or else update_scan_aliases goes berserk because the index
        # will be reset for each combobox in the process. Reconnect after changes.
        cmb: QComboBox
        for key, cmb in self.cmb_scanaliases_dict.items():
            print(f"reset_scan_alias_cmbs resettings for key {key}")
            cmb.currentTextChanged.disconnect(self.update_scan_aliases)
            cmb.currentTextChanged.disconnect(self.is_ready_import)
            cmb.clear()
            cmb.addItems(["Select an alias"] + basenames)
            cmb.currentTextChanged.connect(self.update_scan_aliases)
            cmb.currentTextChanged.connect(self.is_ready_import)

    def update_scan_aliases(self):
        """
        Updates the scan aliases global variable as comboboxes in the scans section are selected
        """
        for key, value in self.cmb_scanaliases_dict.items():
            if value.currentText() != "Select an alias":
                self.scan_aliases[key] = value.currentText()
            else:
                self.scan_aliases[key] = None

    def clear_run_alias_cmbs_and_les(self):
        """
        Removes all row widgets from the runs section. Clears the lineedits dict linking directory names to user-
        preferred aliases. Clears the comboboxes dictionary specifying order.
        """
        for idx in range(self.formlay_runaliases.rowCount()):
            self.formlay_runaliases.removeRow(0)
        self.le_runaliases_dict.clear()
        self.cmb_runaliases_dict.clear()

    def reset_run_aliases(self, basenames=None):
        """
        Resets the entire run section. Clears previous rows if necessary. Resets the global variables for the
        lineedits and comboboxes containing mappings of the basename to the row widgets.
        :param basenames: filepath basenames to populate the row labels with and establish alias mappings with
        """
        if basenames is None:
            basenames = []

        # If this is an update, remove the previous widgets and clear the dict
        if len(self.le_runaliases_dict) > 0:
            self.clear_run_alias_cmbs_and_les()

        # Generate the new dict mappings of directory basename to preferred alias name and mapping
        # runaliases_dict has keys that are the basenames of the path depth corresponding to runs and values that are
        # the lineedit and combobox widgets
        self.le_runaliases_dict = dict.fromkeys(basenames)
        self.cmb_runaliases_dict = dict.fromkeys(basenames)

        # Repopulate the format layout, and establish mappings for the lineedits and the comboboxes
        for ii, key in enumerate(self.le_runaliases_dict):
            hlay = QHBoxLayout()
            cmb = QComboBox()
            cmb.setToolTip(self.import_tips["cmb_runposition"])
            nums_to_add = [str(num) for num in range(1, len(self.le_runaliases_dict) + 1)]
            cmb.addItems(nums_to_add)
            cmb.setCurrentIndex(ii)
            cmb.currentIndexChanged.connect(self.is_ready_import)
            le = QLineEdit(placeholderText="(Optional) Specify the alias for this run")
            le.setToolTip(self.import_tips["le_runalias"] + str(ii))
            hlay.addWidget(le)
            hlay.addWidget(cmb)
            self.formlay_runaliases.addRow(key, hlay)
            # This is where the mappings are re-established
            self.le_runaliases_dict[key] = le
            self.cmb_runaliases_dict[key] = cmb
            if system() == "Darwin":
                le.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                cmb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    ##########################
    # SECTION - MISC FUNCTIONS
    ##########################

    @staticmethod
    def infer_regex(list_of_strings):
        """
        Self-explanatory: deduces a regex string to match a provided list of strings
        :param list_of_strings: the list of string to be matched
        :return: The inferred regex string matching the all the items in the list of strings
        """
        extractor = rexpy.Extractor(list_of_strings)
        extractor.extract()
        regex = extractor.results.rex[0]
        return regex

    @Slot()
    def update_sibling_awareness(self):
        """
        Updates the awareness of what each drop-enabled lineedits contain such that certain variables cannot be dropped
        in for multiple lineedits
        """
        current_texts = [le.text() for le in self.levels.values()]
        for le in self.levels.values():
            le.sibling_awareness = current_texts

    @Slot()
    def is_ready_import(self):
        """
        Quality controls several conditions required in order to be able to run the Importer.
        """
        current_texts = [le.text() for le in self.levels.values()]
        rootpath = Path(self.le_rootdir.text())
        # First requirement; raw directory must be an existent directory without spaces
        if any([not rootpath.exists(), not rootpath.is_dir(), " " in self.le_rootdir.text()]):
            self.btn_run_importer.setEnabled(False)
            return

            # Next requirement; a minimum of "Subject" and "Scan" must be present in the lineedits
        if not all(["Subject" in current_texts, "Scan" in current_texts]):
            self.btn_run_importer.setEnabled(False)
            return

        # Next requirement; at least one scan must be indicated
        cmb_texts: Set[str] = {cmb.currentText() for cmb in self.cmb_scanaliases_dict.values()}
        if len(cmb_texts) <= 1:
            self.btn_run_importer.setEnabled(False)
            return

        # Next requirement; if Run is indicated, the aliases and ordering must both be unique
        if "Run" in current_texts and len(self.cmb_runaliases_dict) > 0:
            current_run_aliases = [le.text() for le in self.le_runaliases_dict.values() if le.text() != '']
            current_run_ordering = [cmb.currentText() for cmb in self.cmb_runaliases_dict.values()]
            if any([
                len(set(current_run_aliases)) != len(current_run_aliases),  # unique aliases requires
                len(set(current_run_ordering)) != len(current_run_ordering)  # unique ordering required
            ]):
                self.btn_run_importer.setEnabled(False)
                return

        self.btn_run_importer.setEnabled(True)

    def set_widgets_on_or_off(self, state: bool):
        """
        Convenience function for turning off widgets during an import run and then re-enabling them afterwards
        :param state: the boolean state of whether the widgets should be enabled or not
        """
        self.btn_run_importer.setEnabled(state)
        self.btn_clear_receivers.setEnabled(state)
        self.btn_setrootdir.setEnabled(state)
        self.le_rootdir.setEnabled(state)

        le: QLineEdit
        for le in self.levels.values():
            le.setEnabled(state)

        cmb: QComboBox
        for cmb in self.cmb_scanaliases_dict.values():
            cmb.setEnabled(state)

    ##################################
    # SECTION - RETRIEVAL OF VARIABLES
    ##################################
    def get_directory_structure(self):
        """
        Returns the directory structure in preparation of running the import
        """
        dirnames = [le.text() for le in self.levels.values()]
        valid_dirs = []
        encountered_nonblank = False
        # Iterate backwards to remove false
        for name in reversed(dirnames):
            # Cannot have blank lines existing between the important directories
            if name == '' and encountered_nonblank:
                robust_qmsg(self, title=self.import_errs["InvalidStructure_Blanks"][0],
                            body=self.progbar_import["InvalidStructure_Blanks"][1])
                return False, []
            elif name == '' and not encountered_nonblank:
                continue
            else:
                encountered_nonblank = True
                valid_dirs.append(name)

        # Sanity check for false user input
        if any(["Subject" not in valid_dirs, "Scan" not in valid_dirs]):
            robust_qmsg(self, title=self.import_errs["InvalidStructure_MinSubScan"][0],
                        body=self.import_errs["InvalidStructure_MinSubScan"][1])
            return False, []

        valid_dirs = list(reversed(valid_dirs))
        # print(valid_dirs)
        return True, valid_dirs

    def get_scan_aliases(self):
        """
        Retrieves a mapping of the standard scan name for ExploreASL (i.e ASL4D) and the user-specifed corresponding
        scan directory
        @return: status, whether the operation was a success; scan_aliases, the mapping
        """
        # Filter out scans that have None to avoid problems down the line
        scan_aliases = {key: value for key, value in self.scan_aliases.items() if value is not None}

        return True, scan_aliases

    def get_run_aliases(self):
        """
        Retrieves a mapping of the run alias names and the user-specified preferred name
        @return: status, whether the operation was a success; run_aliases, the mapping
        """

        run_aliases = OrderedDict()

        # If the run aliases dict is empty, simply return the empty dict, as runs are not mandatory to outline
        if len(self.cmb_runaliases_dict) == 0:
            return True, run_aliases

        # First, make sure that every number is unique:
        current_orderset = [cmb.currentText() for cmb in self.cmb_runaliases_dict.values()]
        if len(current_orderset) != len(set(current_orderset)):
            robust_qmsg(self, title=self.import_errs["InvalidRunAliases"][0],
                        body=self.import_errs["InvalidRunAliases"][1])
            return False, run_aliases

        basename_keys = list(self.le_runaliases_dict.keys())
        aliases = list(le.text() for le in self.le_runaliases_dict.values())
        orders = list(cmb.currentText() for cmb in self.cmb_runaliases_dict.values())

        if self.config["DeveloperMode"]:
            print(f"Inside get_run_aliases, the following variable values were in play prior to generating the "
                  f"run aliases dict:\n"
                  f"basename_keys: {basename_keys}\n"
                  f"aliases: {aliases}\n"
                  f"orders: {orders}")

        for num in range(1, len(orders) + 1):
            idx = orders.index(str(num))
            current_alias = aliases[idx]
            current_basename = basename_keys[idx]
            if current_alias == '':
                run_aliases[current_basename] = f"ASL_{num}"
            else:
                run_aliases[current_basename] = current_alias

        return True, run_aliases

    # Utilizes the other get_ functions above to create the import parameters file
    def get_import_parms(self):
        import_parms = {}.fromkeys(["Regex", "Directory Structure", "Scan Aliases", "Ordered Run Aliases"])
        # Get the directory structure, the scan aliases, and the run aliases
        directory_status, valid_directories = self.get_directory_structure()
        scanalias_status, scan_aliases = self.get_scan_aliases()
        runalias_status, run_aliases = self.get_run_aliases()
        if any([self.subject_regex == '',  # Subject regex must be established
                self.scan_regex == '',  # Scan regex must be established
                not directory_status,  # Getting the directory structure must have been successful
                not scanalias_status,  # Getting the scan aliases must have been successful
                not runalias_status  # Getting the run aliases must have been successful
                ]):
            return None

        # Otherwise, green light to create the import parameters
        import_parms["RawDir"] = self.le_rootdir.text()
        import_parms["Regex"] = [self.subject_regex, self.run_regex, self.scan_regex]
        import_parms["Directory Structure"] = valid_directories
        import_parms["Scan Aliases"] = scan_aliases
        import_parms["Ordered Run Aliases"] = run_aliases

        # Save a copy of the import parms to the raw directory in question
        with open(Path(self.le_rootdir.text()) / "ImportConfig.json", 'w') as w:
            json.dump(import_parms, w, indent=3)

        return import_parms

    #############################################
    # SECTION - CONCURRENT AND POST-RUN FUNCTIONS
    #############################################
    @Slot()
    def slot_update_progressbar(self):
        self.progbar_import.setValue(self.progbar_import.value() + 1)

    @Slot()
    def slot_cleanup_postterminate(self):
        self.n_import_workers -= 1
        if len(self.import_summaries) > 0:
            self.import_summaries.clear()
        if len(self.failed_runs) > 0:
            self.failed_runs.clear()

        # Don't proceed until all importer workers are finished
        if self.n_import_workers > 0 or self.import_parms is None:
            return

        # Reset the widgets and cursor
        self.set_widgets_on_or_off(state=True)
        self.btn_terminate_importer.setEnabled(False)

        analysis_dir = Path(self.import_parms["RawDir"]).parent / "analysis"
        if analysis_dir.exists():
            robust_qmsg(self, title=self.import_errs["CleanupImportPostTerm"][0],
                        body=self.import_errs["CleanupImportPostTerm"][1], variables=[str(analysis_dir)])
        QApplication.restoreOverrideCursor()

    @Slot(list)
    def slot_is_ready_postprocessing(self, signalled_summaries: list):
        """
        Creates the summary file. Increments the "debt" due to launching workers back towards zero. Resets widgets
        once importer workers are done.
        :param signalled_summaries: A list of dicts, each dict being all the relevant DICOM and NIFTI parameters of
        a converted directory
        """
        # Stockpile the completed summaries and increment the "debt" back towards zero
        self.import_summaries.extend(signalled_summaries)
        self.n_import_workers -= 1

        # Don't proceed until all importer workers are finished
        if self.n_import_workers > 0 or self.import_parms is None:
            return

        # Otherwise, proceed to post-import processing
        self.import_postprocessing()

    @Slot(list)
    def slot_update_failed_runs_log(self, signalled_failed_runs: list):
        """
        Updates the attribute failed_runs in order to write the json file summarizing failed runs once everything is
        complete
        :param signalled_failed_runs: A list of dicts, each dict being the name of the DICOM directory attempted for
        conversion and the value being a description of the step in DCM2BIDS that it failed on.
        """
        self.failed_runs.extend(signalled_failed_runs)

    def import_postprocessing(self):
        """
        Performs the bulk of the post-import work, especially if the import type was specified to be BIDS
        """
        print("Clearing Import workers from memory, re-enabling widgets, and resetting current directory")
        self.import_workers.clear()
        self.set_widgets_on_or_off(state=True)
        self.btn_terminate_importer.setEnabled(False)
        QApplication.restoreOverrideCursor()

        chdir(self.config["ScriptsDir"])
        analysis_dir = Path(self.import_parms["RawDir"]).parent / "analysis"
        if not analysis_dir.exists():
            robust_qmsg(self, title=self.import_errs["StudyDirNeverMade"][0],
                        body=self.import_errs["StudyDirNeverMade"][1], variables=[str(analysis_dir)])
            return

        # Concatenate the tmpImport_Converter_###.log files into a single log placed in the study directory
        # Also, remove the log files in the process
        logs = []
        log_files = sorted(Path(self.import_parms["RawDir"]).glob("tmpImport_Converter*.log"))
        for log_file in log_files:
            with open(log_file, "r") as log_reader:
                logs.append(log_reader.read())
            log_file.unlink(missing_ok=True)

        now_str = datetime.now().strftime("%a-%b-%d-%Y_%H-%M-%S")
        try:
            log_path = analysis_dir / "Logs" / "Import Logs" / f"Import_Log_{now_str}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w") as log_writer:
                log_writer.write(f"\n{'#' * 50}\n".join(logs))
        except PermissionError:
            log_path = analysis_dir / "Logs" / "Import Logs" / f"Import_Log_{now_str}_backup.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w") as log_writer:
                log_writer.write("\n\n".join(logs))

        # Create the import summary
        create_import_summary(import_summaries=self.import_summaries, config=self.import_parms)

        # If the settings is BIDS...
        if not self.chk_uselegacy.isChecked():
            # Ensure all M0 jsons have the appropriate "IntendedFor" field if this is in BIDS
            bids_m0_followup(analysis_dir=analysis_dir)

            # Create the template for the dataset description
            self.create_dataset_description_template(analysis_dir)

            # Create the "bidsignore" file
            with open(analysis_dir / ".bidsignore", 'w') as ignore_writer:
                to_ignore = ["Import_Log_*.log\n", "Import_Failed*.txt\n", "Import_Dataframe_*.tsv\n"]
                ignore_writer.writelines(to_ignore)
                del to_ignore

        # If there were any failures, write them to disk now
        if len(self.failed_runs) > 0:
            try:
                with open(analysis_dir / "Import_Failed_Imports.txt", "w") as failed_writer:
                    failed_writer.writelines([line + "\n" for line in self.failed_runs])
                robust_qmsg(self, title=self.import_errs["ImportErrors"][0], body=self.import_errs["ImportErrors"][1],
                            variables=[log_path.name, str(analysis_dir)])
            except FileNotFoundError:
                robust_qmsg(self, title=self.import_errs["StudyDirNeverMade"][0],
                            body=self.import_errs["StudyDirNeverMade"][1], variables=[str(analysis_dir)])
        else:
            # Finally, a Message confirming a successful import
            QMessageBox.information(self, "Import was a Success",
                                    f"You have successfully imported the DICOM dataset into NIFTI format.\n"
                                    f"The study directory is located at:\n{str(analysis_dir)}", QMessageBox.Ok)

    @staticmethod
    def create_dataset_description_template(analysis_dir: Path):
        """
        Creates a template for the dataset description file for the user to complete at a later point in time
        :param analysis_dir: The analysis directory where the dataset description will be saved to.
        """
        template = {
            "BIDSVersion": "0.1.0",
            "License": "CC0",
            "Name": "A multi-subject, multi-modal human neuroimaging dataset",
            "Authors": [],
            "Acknowledgements": "",
            "HowToAcknowledge": "This data was obtained from [owner]. "
                                "Its accession number is [id number]'",
            "ReferencesAndLinks": ["https://www.ncbi.nlm.nih.gov/pubmed/25977808",
                                   "https://openfmri.org/dataset/ds000117/"],
            "Funding": ["UK Medical Research Council (MC_A060_5PR10)"]
        }
        with open(analysis_dir / "dataset_description.json", 'w') as dataset_writer:
            json.dump(template, dataset_writer, indent=3)

    ########################
    # SECTION - RUN FUNCTION
    ########################
    def run_importer(self):
        """
        First confirms that all import parameters are set, then runs ASL2BIDS using multi-threading
        """
        # Set (or reset if this is another run) the essential variables
        self.n_import_workers = 0
        self.import_parms = None
        self.import_summaries.clear()
        self.failed_runs.clear()
        self.import_workers.clear()

        # Disable the run button to prevent accidental re-runs
        self.set_widgets_on_or_off(state=False)

        # Ensure the dcm2niix path is visible
        chdir(Path(self.config["ProjectDir"]) / "External" / "DCM2NIIX" / f"DCM2NIIX_{system()}")

        # Get the import parameters
        self.import_parms = self.get_import_parms()
        if self.import_parms is None:
            # Reset widgets back to normal and change the directory back
            self.set_widgets_on_or_off(state=True)
            chdir(self.config["ScriptsDir"])
            return

        # Get the dicom directories
        subject_dirs: List[Tuple[Path]] = get_dicom_directories(config=self.import_parms)

        # Set the progressbar
        self.progbar_import.setValue(0)
        self.progbar_import.setMaximum(len(list(collapse(subject_dirs))))

        if self.config["DeveloperMode"]:
            print("Detected the following dicom directories:")
            pprint(subject_dirs)
            print('\n')

        NTHREADS = min([len(subject_dirs), 4])
        # NTHREADS = 1  # For troubleshooting
        for idx, subjects_subset in enumerate(divide(NTHREADS, subject_dirs)):
            dicom_dirs = flatten(subjects_subset)
            worker = Importer_Worker(dcm_dirs=dicom_dirs,  # The list of dicom directories
                                     config=self.import_parms,  # The import parameters
                                     use_legacy_mode=self.chk_uselegacy.isChecked(),
                                     name=f"Converter_{str(idx).zfill(3)}"
                                     )  # Whether to use legacy mode or not
            self.signal_stop_import.connect(worker.slot_stop_import)
            worker.signals.signal_send_summaries.connect(self.slot_is_ready_postprocessing)
            worker.signals.signal_send_errors.connect(self.slot_update_failed_runs_log)
            worker.signals.signal_confirm_terminate.connect(self.slot_cleanup_postterminate)
            worker.signals.signal_update_progressbar.connect(self.slot_update_progressbar)
            self.import_workers.append(worker)
            self.n_import_workers += 1

        # Launch them
        for worker in self.import_workers:
            self.threadpool.start(worker)

        # Change the cursor
        self.btn_terminate_importer.setEnabled(True)
        QApplication.setOverrideCursor(Qt.WaitCursor)


class DraggableLabel(QLabel):
    """
    Modified QLabel to support dragging out the text content
    """

    def __init__(self, text='', parent=None):
        super(DraggableLabel, self).__init__(parent)
        self.setText(text)
        style_windows = """
        QLabel {
            border-style: solid;
            border-width: 2px;
            border-color: black;
            border-radius: 10px;
            background-color: white;
        }
        """
        style_unix = """
        QLabel {
            border-style: solid;
            border-width: 2px;
            border-color: black;
            border-radius: 10px;
            background-color: white;
        }
        """
        if system() == "Windows":
            self.setStyleSheet(style_windows)
        else:
            self.setStyleSheet(style_unix)
        font = QFont()
        font.setPointSize(16)
        self.setFont(font)
        # self.setMinimumHeight(75)
        # self.setMaximumHeight(100)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setAlignment(Qt.AlignCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mimedata = QMimeData()
        mimedata.setText(self.text())
        drag.setMimeData(mimedata)
        drag.setHotSpot(event.pos())
        drag.exec_(Qt.CopyAction | Qt.MoveAction)


class DandD_Label2LineEdit(QLineEdit):
    """
    Modified QLineEdit to support accepting text drops from a QLabel with Drag enabled
    """

    modified_text = Signal(str, int)

    def __init__(self, superparent, parent=None, identification: int = None):
        super().__init__(parent)

        self.setAcceptDrops(True)
        self.setReadOnly(True)
        self.superparent = superparent  # This is the Importer Widget itself
        self.sibling_awareness = [''] * 7
        self.id = identification  # This is the python index of which level after ..\\raw does this lineedit represent
        self.textChanged.connect(self.modifiedtextChanged)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasText():
            if all([event.mimeData().text() not in self.sibling_awareness,
                    self.superparent.le_rootdir.text() != '']) or event.mimeData().text() == "Dummy":
                event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasText():
            if all([event.mimeData().text() not in self.sibling_awareness,
                    self.superparent.le_rootdir.text() != '']) or event.mimeData().text() == "Dummy":
                event.accept()
                event.setDropAction(Qt.CopyAction)
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasText():
            if all([event.mimeData().text() not in self.sibling_awareness,
                    self.superparent.le_rootdir.text() != '']) or event.mimeData().text() == "Dummy":
                event.accept()
                self.setText(event.mimeData().text())
        else:
            event.ignore()

    def modifiedtextChanged(self):
        self.modified_text.emit(self.text(), self.id)
