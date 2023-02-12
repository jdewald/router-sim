import os
import shutil
from distutils.sysconfig import get_python_lib
from jupyter_core.command import main

#from needle_notebook.magic import DATA_DIR


if __name__ == "__main__":

    # Link to demo notebooks
    demo_notebook_link_path = "/notebooks/demos"
    if not os.path.exists(demo_notebook_link_path):
        os.symlink(
            "/app/needle_notebook/needle_notebook_py.binary.runfiles/__main__/needle_notebook/demos",
            demo_notebook_link_path
        )

    # Link to custom JS and styles in root user home directory
#    custom_dir_link_path = "/root/.jupyter/custom"
#    if not os.path.exists(custom_dir_link_path):
#        os.symlink(
#            "/app/needle_notebook/needle_notebook_py.binary.runfiles/__main__/needle_notebook/interface",
#            custom_dir_link_path
#        )

    # Copy over custom JS and styles to site packages directory
#    custom_dir = "/app/needle_notebook/needle_notebook_py.binary.runfiles/__main__/needle_notebook/interface"
#    site_packages_dir = get_python_lib()
#    notebook_custom_dir = os.path.join(site_packages_dir, 'notebook/static/custom')

#    os.makedirs(notebook_custom_dir, exist_ok=True)

#    for static_file in ("custom.css", "custom.js"):
#        static_file_src = os.path.join(custom_dir, static_file)
#        static_file_dest = os.path.join(notebook_custom_dir, static_file)
#
#        shutil.copy(static_file_src, static_file_dest)

#    os.makedirs(DATA_DIR, exist_ok=True)
    # Equivalent to `python -m jupyter ...argv`
    main()