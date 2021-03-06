from src.xASL_GUI_MainWin import xASL_MainWin
from src.xASL_GUI_HelperFuncs_WidgetFuncs import robust_qmsg
from PySide2.QtWidgets import QApplication, QMessageBox, QWidget
from PySide2.QtGui import QIcon
from platform import system
from shutil import which
from glob import iglob
from os import chdir
from pathlib import Path
import sys
from json import load
from typing import Union
import subprocess
import re


def get_local_matlab() -> (Union[str, None], Union[str, None]):
    matlab_cmd_path = which("matlab")
    matlab_ver_regex = re.compile(r"R\d{4}[ab]")
    # Get version #
    matlab_ver = None

    # Is on PATH
    if matlab_cmd_path is not None:

        match = matlab_ver_regex.search(matlab_cmd_path)

        # If the version number was found
        if match:
            print(f"shutil method was a success and located: {match.group()}")
            matlab_ver = match.group()
            return matlab_ver, matlab_cmd_path

        # Otherwise,
        # For Linux/MacOS with promising root
        if system() == "Linux" and '/usr/' in matlab_cmd_path:
            print(f"User clearly has the matlab command in {matlab_cmd_path}, but the version number could not be "
                  f"ascertained. Attempting to locate around '/usr/local/")
            for search_pattern in ["/usr/local/matlab**/bin", "/usr/local/**/MATLAB/*/bin",
                                   "/home/.local/matlab**/bin", "/home/.local/**/MATLAB/*/bin"]:
                try:
                    local_result = next(iglob(search_pattern, recursive=True))
                    local_match = matlab_ver_regex.search(local_result[0])
                    if local_match:
                        matlab_ver = local_match.group()
                        return matlab_ver, matlab_cmd_path
                except StopIteration:
                    continue

        # If no luck so far, resort to using subprocess since matlab is on PATH
        if matlab_ver is None:
            print("Version was not readily visible in PATH. Attempting backup subprocess method to extract version")
            result = subprocess.run(["matlab", "-nosplash", "-nodesktop", "-batch", "matlabroot"],
                                    capture_output=True, text=True)
            match = matlab_ver_regex.search(str(result.stdout))
            if result.returncode == 0 and match:
                matlab_ver = match.group()
            return matlab_ver, matlab_cmd_path

        # Windows or no lucky search pattern
        return matlab_ver, matlab_cmd_path

    # Not on PATH
    else:
        if system() != "Darwin":
            return matlab_ver, matlab_cmd_path
        # MacOS, default installation to Applications seems to avoid adding MATLAB to PATH. Look for it in applications
        applications_path = Path("/Applications").resolve()
        try:
            matlab_cmd_path = str(next(applications_path.rglob("bin/matlab")))
            matlab_ver = matlab_ver_regex.search(matlab_cmd_path).group()
            return matlab_ver, matlab_cmd_path
        except (StopIteration, AttributeError):
            return matlab_ver, matlab_cmd_path


def startup():
    app = QApplication(sys.argv)
    screen = app.primaryScreen()
    screen_size = screen.availableSize()
    project_dir = Path(__file__).resolve().parent.parent
    print(f"Launching script at: {Path(__file__)} ")
    print(f"Project Directory is: {project_dir}")

    # Get the appropriate default style based on the user's operating system
    app.setStyle("Fusion") if system() in ["Windows", "Linux"] else app.setStyle("macintosh")

    # Ensure essential directories exist
    for essential_dir in ["JSON_LOGIC", "media", "External"]:
        if not (project_dir / essential_dir).exists():
            QMessageBox().warning(QWidget(),
                                  f"No {essential_dir} directory found",
                                  f"The program directory structure is compromised. "
                                  f"No {essential_dir} directory was located in {project_dir}",
                                  QMessageBox.Ok)
            sys.exit(1)

    # Check if the master config file exists; if it doesn't, the app will initialize one on the first startup
    if (project_dir / "JSON_LOGIC" / "ExploreASL_GUI_masterconfig.json").exists():
        print("Loading masterconfig file.")
        with open(project_dir / "JSON_LOGIC" / "ExploreASL_GUI_masterconfig.json") as master_config_reader:
            master_config = load(master_config_reader)
        # Update the ProjectDir and ScriptsDir variables in the event the user moves the location of this folder
        # First, make sure the Startup.py is located in the src folder
        if project_dir != master_config["ProjectDir"]:
            master_config["ProjectDir"] = str(project_dir)
            master_config["ScriptsDir"] = str(project_dir / "src")

    # Otherwise, this is a first time startup and additional things need to be checked
    else:
        master_config = {"ExploreASLRoot": "",  # The filepath to the ExploreASL directory
                         "DefaultRootDir": str(Path.home()),  # The default root for the navigator to watch from
                         "ScriptsDir": str(project_dir / "src"),  # The location of where this script is launched from
                         "ProjectDir": str(project_dir),  # The location of the src main dir
                         "Platform": f"{system()}",
                         "ScreenSize": (screen_size.width(), screen_size.height()),  # Screen dimensions
                         "DeveloperMode": True}  # Whether to launch the app in developer mode or not

        # TODO Okay, this is no longer sufficient in light of compatibility with the compiled version. Consider a custom
        #  QMessageBox, perhaps?
        # We must also check for the MATLAB version present on the machine
        desc = "Is a standard MATLAB program installed on this machine?"
        check_for_local = QMessageBox.question(QWidget(), "MATLAB Detection", desc,
                                               (QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel))
        if check_for_local == QMessageBox.Cancel:
            sys.exit(0)

        if check_for_local == QMessageBox.Yes:
            version, cmd_path = get_local_matlab()
            master_config["MATLAB_VER"] = version
            master_config["MATLAB_CMD_PATH"] = cmd_path
            if cmd_path is None:
                robust_qmsg(None, "warning", "No MATLAB Command Found",
                            "The matlab command could not be located on this system. Please use the main window's "
                            "menu to manually specify where it is located if you wish to use a non-compiled ExploreASL")
            elif cmd_path is not None and version is None:
                # This should never print. Once matlab is located properly, the matlabroot command will display R####
                robust_qmsg(None, "warning", "No MATLAB Version Found",
                            ["The matlab command was found at:\n", "\nHowever, the version could not be determined."],
                            [cmd_path])
            else:
                robust_qmsg(None, "information", "Local MATLAB Location & Version discerned",
                            ["Detected the matlab path to be:\n", "\nDetected the matlab version to be: "],
                            [cmd_path, version])
        else:
            body_txt = "See which applies to you:\n1) If you intend to use MATLAB at a later point in time, you " \
                       "will have the option to specify its location in the Main Window of this program." \
                       "\n\n2) If you do not intend use a MATLAB Installation, you will need to download the MATLAB " \
                       "Runtime as well as the compiled version of ExploreASL, then specify the filepaths to these" \
                       "when defining Study Parameters. At the current time, the compiled version only supports the " \
                       "2019a Runtime."
            robust_qmsg(None, "information", "Instructions for non-MATLAB cases", body_txt)

        # Assuming the above was successful, dcm2niix may not have executable permission; add execute permissions
        dcm2niix_dir = project_dir / "External" / "DCM2NIIX" / f"DCM2NIIX_{system()}"
        dcm2niix_file = next(dcm2niix_dir.glob("dcm2niix*"))
        stat = oct(dcm2niix_file.stat().st_mode)
        if not stat.endswith("775"):
            dcm2niix_file.chmod(0o775)
        else:
            print(f"dcm2niix already has execute permissions")

    # If all was successful, launch the GUI
    app.setWindowIcon(QIcon(str(project_dir / "media" / "ExploreASL_logo.ico")))
    chdir(project_dir / "src")

    # Memory cleanup
    del project_dir

    main_win = xASL_MainWin(master_config)
    main_win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    startup()
