# Wiggler  
The wiggler is a Maya auto-secondary tool for animators, developed in python.  
  
<p align="center">
  <img align="center" height="500" src="https://github.com/user-attachments/assets/ed79eca6-c489-496f-a7d4-38918b8ff4b2">
</p>
  
## Requirements:
This tool requires the following python packages: [dcc](https://github.com/bhsingleton/dcc) and [mpy](https://github.com/bhsingleton/mpy).  
When downloading these packages from Github make sure to unzip the contents into the Maya scripts folder located inside your user documents folder.  
It is important to remove any prefixes from the unzipped folder name: `dcc-main` > `dcc`, otherwise the tools will fail to run!  
  
The following plug-in: [boneDynamicsNode](https://github.com/akasaki1211/boneDynamicsNode), is also required as well.  
Unzip the release files and copy the `.mll` file that matches the version of Maya you are using.  
Next, go to the Maya user documents location and locate the subfolder that matches the version of Maya you are using.  
Finally, paste the `.mll` into a `plug-ins` folder. If no `plug-ins` folder exists then go ahead and create one!  
  
## How to open:
Run the following python code from the script editor or from a shelf button:  
  
```
from wiggler.ui import qwiggler

window = qwiggler.QWiggler()
window.show()
```
