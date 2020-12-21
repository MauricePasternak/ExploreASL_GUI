from PySide2.QtWidgets import *
from PySide2.QtGui import *
from PySide2.QtCore import *
from src.xASL_GUI_HelperFuncs_WidgetFuncs import set_widget_icon
from src.xASL_GUI_HelperClasses import DandD_FileExplorer2LineEdit
from src.xASL_GUI_HelperFuncs_StringOps import set_os_dependent_text
import os
import shutil
from pathlib import Path


class xASL_FileExplorer(QWidget):
    def __init__(self, parent):
        super().__init__(parent=parent)
        self.config = parent.config
        self.path_history = []  # List of Path objects
        self.path_index = 0

        # Define the lineedit of the current directory
        self.le_current_dir = DandD_FileExplorer2LineEdit(acceptable_path_type="Directory")
        self.le_current_dir.editingFinished.connect(self.go_from_text)

        # Define the buttons that will be used to navigate through the directories
        self.hlay_btns = QHBoxLayout()
        self.btn_back = QPushButton(clicked=self.go_back)
        self.btn_up = QPushButton(clicked=self.go_up)
        self.btn_forward = QPushButton(clicked=self.go_forward)
        for btn, icon_name, tip in zip([self.btn_back, self.btn_up, self.btn_forward],
                                       ["arrow_left_encircled.svg", "arrow_up_encircled.svg",
                                        "arrow_right_encircled.svg"],
                                       ["Press to go back in your filepaths visited history",
                                        "Press to go up a directory level",
                                        "Press to go forward in your filepaths visited history"]
                                       ):
            set_widget_icon(widget=btn, config=self.config, icon_name=icon_name, size=(25, 25))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            btn.setToolTip(tip)
            self.hlay_btns.addWidget(btn)

        # Define the file system model and its display container
        self.treev_file = xASL_FileView()
        self.treev_file.setContextMenuPolicy(Qt.CustomContextMenu)
        self.treev_file.customContextMenuRequested.connect(self.menuContextTree)
        self.model_file = QFileSystemModel()

        self.model_file.setRootPath(str(self.config["DefaultRootDir"]))
        self.treev_file.setModel(self.model_file)
        self.treev_file.setRootIndex(self.model_file.index(str(self.config["DefaultRootDir"])))
        self.treev_file.header().resizeSection(0, 250)
        self.treev_file.setDragEnabled(True)
        self.treev_file.setSortingEnabled(True)
        self.treev_file.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.treev_file.sortByColumn(1, Qt.AscendingOrder)
        self.treev_file.setExpandsOnDoubleClick(False)
        self.treev_file.setAnimated(True)
        self.treev_file.doubleClicked.connect(self.go_down)
        self.treev_file.setMinimumWidth(500)
        self.treev_file.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # self.path_history.append(self.config["DefaultRootDir"].replace("\\", "/"))
        self.path_history.append(Path(self.config["DefaultRootDir"]))
        set_os_dependent_text(linedit=self.le_current_dir,
                              config_ossystem=self.config["Platform"],
                              text_to_set=self.config["DefaultRootDir"])

        # With the model defined, define the auto-completer class
        self.completer_current_dir = QCompleter(completionMode=QCompleter.InlineCompletion)
        self.completer_current_dir.setModel(self.model_file)
        self.le_current_dir.setCompleter(self.completer_current_dir)

        # Define main layout and add components to it
        self.mainlay = QVBoxLayout(self)
        self.mainlay.addWidget(self.le_current_dir)
        self.mainlay.addLayout(self.hlay_btns)
        self.mainlay.addWidget(self.treev_file)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def menuContextTree(self, point):
        # Infos about the node selected.
        index = self.treev_file.indexAt(point)

        if not index.isValid():
            menu = QMenu()
            paste_action = menu.addAction(QIcon.fromTheme("edit-paste"), "Paste")
            paste_action.triggered.connect(self.menu_based_paste)
            menu.exec_(self.treev_file.mapToGlobal(point))
            return

        # We build the menu.
        menu = QMenu()
        media_dir = Path(self.config["ProjectDir"]) / "media"
        delete_action = menu.addAction(QIcon.fromTheme("edit-delete"), "Delete")
        delete_action.triggered.connect(self.menu_based_delete)
        copy_action = menu.addAction(QIcon.fromTheme("edit-copy"), "Copy")
        copy_action.triggered.connect(self.menu_based_copy)
        paste_action = menu.addAction(QIcon.fromTheme("edit-paste"), "Paste")
        paste_action.triggered.connect(self.menu_based_paste)
        rename_action = menu.addAction(QIcon(str(media_dir / "rename_icon.png")), "Rename")
        rename_action.triggered.connect(self.menu_based_rename)
        menu.exec_(self.treev_file.mapToGlobal(point))

    # Hack, this method of calling the event prevents automatic triggering
    def menu_based_delete(self):
        self.treev_file.delete_event()

    # Hack, this method of calling the event prevents automatic triggering
    def menu_based_copy(self):
        self.treev_file.copy_event()

    # Hack, this method of calling the event prevents automatic triggering
    def menu_based_paste(self):
        self.treev_file.paste_event()

    def menu_based_rename(self):
        self.treev_file.begin_rename_event()

    def path_change(self, newpath: Path, current_index: int):
        try:
            # If the newpath is not the same as the path ahead (i.e if returning forward or up or down), clear the
            # path history ahead
            if self.path_history[current_index + 1] != newpath:
                for idx in range(current_index, len(self.path_history)):
                    del self.path_history[current_index + 1]
                # self.treev_file.setRootIndex(self.model_file.index(newpath.replace('\\', '/')))
                self.treev_file.setRootIndex(self.model_file.index(str(newpath)))
                # set_os_dependent_text(linedit=self.le_current_dir,
                #                       config_ossystem=self.config["Platform"],
                #                       text_to_set=str(newpath))
                self.le_current_dir.setText(str(newpath))
                self.model_file.setRootPath(str(newpath))
            # Otherwise, proceed as normal
            else:
                self.treev_file.setRootIndex(self.model_file.index(str(newpath)))
                # set_os_dependent_text(linedit=self.le_current_dir,
                #                       config_ossystem=self.config["Platform"],
                #                       text_to_set=str(newpath))
                self.le_current_dir.setText(str(newpath))
                self.model_file.setRootPath(str(newpath))
        # If an index error was encountered, we must be at the head of the path history and there is no need to worry
        # about looking ahead
        except IndexError:
            # self.treev_file.setRootIndex(self.model_file.index(newpath.replace('\\', '/')))
            self.treev_file.setRootIndex(self.model_file.index(str(newpath)))
            set_os_dependent_text(linedit=self.le_current_dir,
                                  config_ossystem=self.config["Platform"],
                                  text_to_set=str(newpath))
            self.model_file.setRootPath(str(newpath))

    # Enter a path in the lineedit and press Enter
    def go_from_text(self):
        # newpath = self.le_current_dir.text().replace('\\', '/')
        newpath = Path(self.le_current_dir.text())

        # Avoid writing into history if the Enter event is the current directory
        if newpath == self.path_history[self.path_index]:
            return

        # if os.path.exists(newpath):
        if newpath.exists():
            # if os.path.isdir(newpath):
            if newpath.is_dir():
                self.path_change(newpath=newpath, current_index=self.path_index)
                try:
                    if self.path_history[self.path_index + 1] == newpath:
                        self.path_index += 1
                    else:
                        print("go_from_text; this should never print")
                except IndexError:
                    self.path_history.append(newpath.replace('\\', '/'))
                    self.path_index += 1

                self.dev_path_print("Pressed Enter into a new directory")
            else:
                QMessageBox().warning(self,
                                      "Cannot Enter into a file",
                                      f"The File Explorer detected that the path you entered:\n{newpath}\nis a file. "
                                      f"This program is not able to open files from this location at the current time")
                # Reset the lineedit back to the text prior to the Enter event
                set_os_dependent_text(linedit=self.le_current_dir,
                                      config_ossystem=self.config["Platform"],
                                      text_to_set=self.path_history[self.path_index])
                return
        else:
            QMessageBox().warning(self,
                                  "Path does not exist",
                                  f"The File Explorer could not find the path:\n{newpath}",
                                  QMessageBox.Ok)
            # Reset the lineedit back to the text prior to the Enter event
            set_os_dependent_text(linedit=self.le_current_dir,
                                  config_ossystem=self.config["Platform"],
                                  text_to_set=str(self.path_history[self.path_index]))
            return

    # Go up a directory
    def go_up(self):
        # current_root = self.model_file.filePath(self.treev_file.rootIndex())
        current_root = Path(self.model_file.filePath(self.treev_file.rootIndex()))
        # dirname = os.path.dirname(current_root)
        # if os.path.exists(dirname):
        if current_root.parent.exists() and current_root.parent.is_dir():
            # if os.path.isdir(dirname) and
            # any([os.path.dirname(dirname) != dirname, dirname != self.path_history[-1]]):
            if current_root.parent != self.path_history[-1]:
                # self.path_change(newpath=dirname, current_index=self.path_index)
                self.path_change(newpath=current_root.parent, current_index=self.path_index)
                try:
                    # if self.path_history[self.path_index + 1] == dirname:
                    if self.path_history[self.path_index + 1] == current_root.parent:
                        self.path_index += 1
                    else:
                        print("go_up; this should never print")
                except IndexError:
                    # self.path_history.append(dirname.replace('\\', '/'))
                    self.path_history.append(current_root.parent)
                    self.path_index += 1

        self.dev_path_print("Pressed go_up")

    # Go into a directory or open a file
    # noinspection PyCallByClass
    def go_down(self, filepath_modelindex: QModelIndex):
        # filepath = self.model_file.filePath(filepath_modelindex)
        filepath = Path(self.model_file.filePath(filepath_modelindex))
        # User wants to open a directory
        # if os.path.isdir(filepath):
        if filepath.is_dir():
            self.path_change(newpath=filepath, current_index=self.path_index)
            try:
                if self.path_history[self.path_index + 1] == filepath:
                    self.path_index += 1
                else:
                    print("go_down; this should never print")
            except IndexError:
                # self.path_history.append(filepath.replace('\\', '/'))
                self.path_history.append(filepath)
                self.path_index += 1
            self.dev_path_print("Double-clicked to go down into a directory")

        # User wants to open a file
        # elif os.path.isfile(filepath):
        elif filepath.is_file():
            result = QDesktopServices.openUrl(QUrl.fromLocalFile(str(filepath)))
            self.dev_path_print("Attempted to open a file")
            if not result:
                QMessageBox().warning(self.parent(),
                                      "Could not open file",
                                      "Please ensure you have defined a default program to open this type of file in "
                                      "your machine's settings.",
                                      QMessageBox.Ok)
        # Something went wrong
        else:
            print(f"The filepath: {filepath} is not a directory that can be entered into")

    def go_back(self):
        if self.path_index != 0:  # cannot be at the beginning of the history
            # previous_path = self.path_history[self.path_index - 1]
            previous_path: Path = self.path_history[self.path_index - 1]
            # if os.path.exists(previous_path):
            #     if os.path.isdir(previous_path):
            if previous_path.exists() and previous_path.is_dir():
                # self.treev_file.setRootIndex(self.model_file.index(previous_path))
                self.treev_file.setRootIndex(self.model_file.index(str(previous_path)))
                self.path_index -= 1
                # set_os_dependent_text(linedit=self.le_current_dir,
                #                       config_ossystem=self.config["Platform"],
                #                       text_to_set=previous_path)
                self.le_current_dir.setText(str(previous_path))
                self.model_file.setRootPath(str(previous_path))

        self.dev_path_print("Pressed go_back")

    def go_forward(self):
        if self.path_index != (len(self.path_history) - 1):
            # forward_path = self.path_history[self.path_index + 1]
            forward_path: Path = self.path_history[self.path_index + 1]
            # if os.path.exists(forward_path):
            #     if os.path.isdir(forward_path):
            if forward_path.exists() and forward_path.is_dir():
                # self.treev_file.setRootIndex(self.model_file.index(forward_path))
                self.treev_file.setRootIndex(self.model_file.index(str(forward_path)))
                self.path_index += 1
                # set_os_dependent_text(linedit=self.le_current_dir,
                #                       config_ossystem=self.config["Platform"],
                #                       text_to_set=forward_path)
                self.le_current_dir.setText(str(forward_path))
                self.model_file.setRootPath(str(forward_path))

        self.dev_path_print("Pressed go_forward")

    ############################################################################
    # DEVELOPER FUNCTIONS FOR WHEN RUNNING IN DEVELOPER MODE FOR TROUBLESHOOTING
    ############################################################################

    def dev_path_print(self, func_descrption=''):
        # Dev troubleshooting
        if self.config["DeveloperMode"]:
            print(func_descrption)
            print(f"self.path_history={self.path_history}")
            print(f"self.path_index={self.path_index}")
            print(f"current directory post-change: {self.model_file.filePath(self.treev_file.rootIndex())}")
            print("----------------------------\n")


# noinspection PyCallingNonCallable
class xASL_FileView(QTreeView):
    """
    Slightly altered QTreeview to allow for more user-friendly functionality relative to the default implementation.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.pressed_keys = []
        self.copy_buffer = []
        self.is_busy = False
        self.threadpool = QThreadPool()
        self.idx_of_editor = None
        self.orig_filepath = None
        self.editor = None

    def mouseDoubleClickEvent(self, event):
        """
        Altered double-click to only operate based on left clicks, not right clicks.
        @param event: QMouseEvent that triggered this slot.
        """
        if event.button() == Qt.RightButton:
            return
        else:
            super(xASL_FileView, self).mouseDoubleClickEvent(event)

    @Slot()
    def no_longer_busy(self):
        print("File operation was completed. Resetting 'is busy' variable back to False")
        self.is_busy = False
        QApplication.restoreOverrideCursor()

    def delete_event(self):
        if self.is_busy:
            return
        # selected_items = {self.model().filePath(model_idx) for model_idx in self.selectedIndexes()}
        selected_items = {Path(self.model().filePath(model_idx)) for model_idx in self.selectedIndexes()}
        selected_items = list(selected_items)
        print(f"Deleting items: {selected_items}")
        worker = xASL_FileWorker(srcs=selected_items, dst=None, task="Delete")
        worker.signals.signal_done_processing.connect(self.no_longer_busy)
        self.is_busy = True
        self.threadpool.start(worker)
        QApplication.setOverrideCursor(Qt.WaitCursor)

    def copy_event(self):
        if self.is_busy:
            return
        # selected_items = {self.model().filePath(model_idx) for model_idx in self.selectedIndexes()}
        selected_items = {Path(self.model().filePath(model_idx)) for model_idx in self.selectedIndexes()}
        selected_items = list(selected_items)
        print(f"Copying items: {selected_items}")
        self.copy_buffer.clear()
        self.copy_buffer.extend(selected_items.copy())

    def paste_event(self):
        # current_dir = self.model().rootPath()
        # print(f"{current_dir=}")
        current_dir = Path(self.model().rootPath())
        worker = xASL_FileWorker(srcs=self.copy_buffer.copy(), dst=current_dir, task="Paste")
        worker.signals.signal_done_processing.connect(self.no_longer_busy)
        self.is_busy = True
        self.threadpool.start(worker)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.copy_buffer.clear()

    def begin_rename_event(self):
        try:
            selected_model_idx = self.selectedIndexes()[0]
            # self.orig_filepath = self.model().filePath(selected_model_idx)
            self.orig_filepath: Path = Path(self.model().filePath(selected_model_idx))
        except IndexError:
            return
        self.openPersistentEditor(selected_model_idx)
        self.editor: QLineEdit = self.indexWidget(selected_model_idx)
        self.idx_of_editor = selected_model_idx

    def end_rename_event(self):
        proposed_basename = self.editor.text()
        # orig_dirname = os.path.dirname(self.orig_filepath)
        # proposed_filepath = os.path.join(orig_dirname, proposed_basename)
        proposed_filepath: Path = self.orig_filepath.with_name(proposed_basename)
        # _, proposed_filepath_ext = os.path.splitext(proposed_filepath)
        # _, orig_ext = os.path.splitext(self.orig_filepath)

        # if proposed_filepath == self.orig_filepath:
        if proposed_basename == self.orig_filepath.name:
            self.full_close_editor()
            return

        # if os.path.exists(proposed_filepath):
        if proposed_filepath.exists():
            QMessageBox.information(self, "Directory already exists",
                                    f"The specified name {proposed_basename} already exists within:\n"
                                    f"{orig_dirname}\n"
                                    f"Please specify a different name")
            self.full_close_editor()
            return

        # If it is a directory
        # if os.path.isdir(self.orig_filepath):
        if self.orig_filepath.is_dir():
            try:
                # os.rename(self.orig_filepath, proposed_filepath)
                self.orig_filepath.rename(proposed_filepath)
            except FileNotFoundError:
                QMessageBox.information(self, "Illegal file or directory name specified",
                                        f"The specified name {proposed_basename} is not a valid path ending for "
                                        f"this operating system")
            self.full_close_editor()
            return

        # If it is a file
        else:
            # if proposed_filepath_ext == "":
            #     proposed_filepath += orig_ext
            if proposed_filepath.suffix == "":
                proposed_filepath = proposed_filepath.with_suffix(self.orig_filepath.suffix)
            try:
                # os.rename(self.orig_filepath, proposed_filepath)
                self.orig_filepath.rename(proposed_filepath)
            except FileNotFoundError:
                QMessageBox.information(self, "Illegal file or directory name specified",
                                        f"The specified name {proposed_basename} is not a valid path ending for "
                                        f"this operating system")
            self.full_close_editor()
            return

    def full_close_editor(self):
        self.closeEditor(self.editor, QAbstractItemDelegate.NoHint)
        self.closePersistentEditor(self.idx_of_editor)
        self.idx_of_editor = None
        self.orig_filepath = None
        self.editor = None
        return

    def keyPressEvent(self, event: QKeyEvent):
        # Conditions to break early
        if any([event.isAutoRepeat(), self.is_busy, event.key() in self.pressed_keys]):
            return

        print("Key Pressed")
        self.pressed_keys.append(event.key())

        # Initiate delete
        if all([len(self.pressed_keys) == 1, Qt.Key_Delete in self.pressed_keys]):
            print("Attempting to initiate delete event")
            self.delete_event()
            self.pressed_keys.clear()

        # Initiate copy
        elif all([len(self.pressed_keys) == 2,
                  Qt.Key_Control in self.pressed_keys and Qt.Key_C in self.pressed_keys]):
            print("Attempting to initiate copy event")
            self.copy_event()
            self.pressed_keys.clear()

        # Initiate paste
        elif all([len(self.copy_buffer) > 0,
                  len(self.pressed_keys) == 2,
                  Qt.Key_Control in self.pressed_keys and Qt.Key_V in self.pressed_keys]):
            print("Attempting to initiate paste event")
            self.paste_event()
            self.pressed_keys.clear()

        elif all([self.idx_of_editor is not None,
                  event.key() == Qt.Key_Return]):
            print("Attempting to complete rename event")
            self.end_rename_event()
            self.pressed_keys.clear()

        else:
            print("Nothing was done:")
            print(f"{self.pressed_keys=}")
            print(f"{self.copy_buffer=}")
            print(f"{self.is_busy=}")
            pass

        super(xASL_FileView, self).keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if any([event.isAutoRepeat(), self.is_busy]):
            return

        try:
            del self.pressed_keys[-1]
        except IndexError:
            self.pressed_keys.clear()

        super(xASL_FileView, self).keyReleaseEvent(event)


class xASL_FileWorker_Signals(QObject):
    signal_done_processing = Signal()


class xASL_FileWorker(QRunnable):
    def __init__(self, srcs, dst, task):
        super().__init__()
        self.signals = xASL_FileWorker_Signals()
        self.srcs = srcs
        self.dst: Path = dst
        self.task = task

    def run(self):
        if self.task == "Delete":
            filepath: Path
            for filepath in self.srcs:
                # if os.path.isfile(filepath):
                #     os.remove(filepath)
                if filepath.is_file():
                    filepath.unlink(missing_ok=True)
                else:
                    shutil.rmtree(filepath, ignore_errors=True)

        elif self.task == "Paste":
            for filepath in self.srcs:
                copy_flag = True
                copy_number = 1

                # If it is a file
                # if os.path.isfile(filepath):
                if filepath.is_file():
                    try:
                        # dst = os.path.join(self.dst, os.path.basename(filepath))
                        # shutil.copyfile(filepath, dst)
                        shutil.copyfile(filepath, self.dst / filepath.name)
                    except shutil.SameFileError:

                        # Increment the copy string until it no longer spawns the SameFileError
                        while copy_flag:
                            if copy_number == 1:
                                copy_str = " - Copy"
                            else:
                                copy_str = f" - Copy_{copy_number}"

                            try:
                                # fileparts = os.path.splitext(os.path.basename(filepath))
                                # dst = os.path.join(self.dst, fileparts[0] + copy_str + fileparts[1])
                                dst: Path = self.dst / (filepath.stem + copy_str + filepath.suffix)
                                # if os.path.exists(dst):
                                if dst.exists():
                                    copy_number += 1
                                    continue
                                shutil.copyfile(filepath, dst)
                                copy_flag = False
                            except shutil.SameFileError:
                                copy_number += 1
                                print(f"Incremented copy_number to {copy_number}")
                # If it is a folder
                else:
                    try:
                        # dst = os.path.join(self.dst, os.path.basename(filepath))
                        # shutil.copytree(filepath, dst)
                        shutil.copytree(filepath, self.dst / filepath.name)
                    except FileExistsError:

                        # Increment the copy string until it no longer spawns the SameFileError
                        while copy_flag:
                            if copy_number == 1:
                                copy_str = " - Copy"
                            else:
                                copy_str = f" - Copy_{copy_number}"
                            try:
                                # dst = os.path.join(self.dst, os.path.basename(filepath + copy_str))
                                # shutil.copytree(filepath, dst)
                                shutil.copytree(filepath, self.dst / (filepath.name + copy_str))
                                copy_flag = False
                            except FileExistsError:
                                copy_number += 1
        else:
            pass

        self.signals.signal_done_processing.emit()
