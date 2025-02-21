import os
import json

from maya import cmds as mc
from maya.api import OpenMaya as om
from mpy import mpyscene, mpynode
from enum import IntEnum
from collections import deque, defaultdict
from dcc.ui import qsingletonwindow, qtimespinbox, qsignalblocker
from dcc.python import stringutils, pathutils
from dcc.maya.libs import pluginutils
from dcc.maya.decorators import animate, undo
from dcc.generators.inclusiverange import inclusiveRange
from dcc.vendor.Qt import QtCore, QtWidgets, QtGui, QtCompat
from . import resources
from ..libs import sceneutils

import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def onSelectionChanged(*args, **kwargs):
    """
    Callback method for any selection changes.

    :rtype: None
    """

    # Check if instance exists
    #
    instance = QWiggler.getInstance()

    if instance is None:

        return

    # Evaluate if instance is still valid
    #
    if QtCompat.isValid(instance):

        instance.selectionChanged(*args, **kwargs)

    else:

        log.warning('Unable to process selection changed callback!')


def onSceneChanged(*args, **kwargs):
    """
    Callback method for any scene IO changes.

    :rtype: None
    """

    # Check if instance exists
    #
    instance = QWiggler.getInstance()

    if instance is None:

        return

    # Evaluate if instance is still valid
    #
    if QtCompat.isValid(instance):

        instance.sceneChanged(*args, **kwargs)

    else:

        log.warning('Unable to process scene changed callback!')


class Column(IntEnum):
    """
    Enum class of the available column headers.
    """

    CONTROL = 0
    JOINT = 1
    JOINT_TIP = 2
    DYNAMICS = 3


class QWiggler(qsingletonwindow.QSingletonWindow):
    """
    Overload of `QUicWindow` that interfaces with bone dynamic nodes.
    """

    # region Dunderscores
    __namespace__ = 'SIM'
    __plugins__ = ('boneDynamicsNode',)

    def __init__(self, *args, **kwargs):
        """
        Private method called after a new instance has been created.

        :key parent: QtWidgets.QWidget
        :key flags: QtCore.Qt.WindowFlags
        :rtype: None
        """

        # Call parent method
        #
        super(QWiggler, self).__init__(*args, **kwargs)

        # Declare private variables
        #
        self._scene = mpyscene.MPyScene.getInstance(asWeakReference=True)
        self._selection = []
        self._selectionCount = 0
        self._activeTreeWidgetItem = None
        self._clearSelection = False
        self._presetsDirectory = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'presets'))
        self._presets = {}
        self._ground = None
        self._callbackIds = om.MCallbackIdArray()

    def __post_init__(self, *args, **kwargs):
        """
        Private method called after an instance has initialized.

        :rtype: None
        """

        # Call parent method
        #
        super(QWiggler, self).__post_init__(*args, **kwargs)

        # Load required plugins
        #
        self.loadPlugins()

        # Update internal selection tracker
        #
        self.invalidatePresets()
        self.invalidateSelection()

    def __setup_ui__(self, *args, **kwargs):
        """
        Private method that initializes the user interface.

        :rtype: None
        """

        # Call parent method
        #
        super(QWiggler, self).__setup_ui__(self, *args, **kwargs)

        # Initialize main window
        #
        self.setWindowTitle("|| Wiggler'mania")
        self.setMinimumSize(QtCore.QSize(400, 750))
        self.setWindowIcon(QtGui.QIcon(':/wiggler/icons/window.png'))

        # Initialize central widget
        #
        centralLayout = QtWidgets.QVBoxLayout()
        centralLayout.setObjectName('centralLayout')

        centralWidget = QtWidgets.QWidget()
        centralWidget.setObjectName('centralWidget')
        centralWidget.setLayout(centralLayout)

        self.setCentralWidget(centralWidget)

        # Initialize selection group-box
        #
        self.selectionLayout = QtWidgets.QGridLayout()
        self.selectionLayout.setObjectName('selectionLayout')

        self.selectionGroupBox = QtWidgets.QGroupBox('Selection:')
        self.selectionGroupBox.setObjectName('selectionGroupBox')
        self.selectionGroupBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding))
        self.selectionGroupBox.setLayout(self.selectionLayout)

        self.selectionTreeWidget = QtWidgets.QTreeWidget()
        self.selectionTreeWidget.setObjectName('selectionTreeWidget')
        self.selectionTreeWidget.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding))
        self.selectionTreeWidget.setExpandsOnDoubleClick(False)
        self.selectionTreeWidget.setAlternatingRowColors(True)
        self.selectionTreeWidget.setHeaderLabels([column.name.title() for column in Column])
        self.selectionTreeWidget.setHeaderHidden(True)
        self.selectionTreeWidget.hideColumn(Column.JOINT)
        self.selectionTreeWidget.hideColumn(Column.JOINT_TIP)
        self.selectionTreeWidget.hideColumn(Column.DYNAMICS)

        self.addSelectionPushButton = QtWidgets.QPushButton('Add Selection')
        self.addSelectionPushButton.setObjectName('addSelectionPushButton')
        self.addSelectionPushButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.addSelectionPushButton.setFixedHeight(24)
        self.addSelectionPushButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.addSelectionPushButton.setToolTip('Adds the selected controls to the tree view.')
        self.addSelectionPushButton.clicked.connect(self.on_addSelectionPushButton_clicked)

        self.appendSelectionPushButton = QtWidgets.QPushButton('Append Selection')
        self.appendSelectionPushButton.setObjectName('appendSelectionPushButton')
        self.appendSelectionPushButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.appendSelectionPushButton.setFixedHeight(24)
        self.appendSelectionPushButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.appendSelectionPushButton.setToolTip('Appends the selected controls to the selected tree item.')
        self.appendSelectionPushButton.clicked.connect(self.on_appendSelectionPushButton_clicked)

        self.removeSelectionButton = QtWidgets.QPushButton('Remove Selection')
        self.removeSelectionButton.setObjectName('removeSelectionButton')
        self.removeSelectionButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.removeSelectionButton.setFixedHeight(24)
        self.removeSelectionButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.removeSelectionButton.setToolTip('Removes the selected tree item from the view.')
        self.removeSelectionButton.clicked.connect(self.on_removeSelectionPushButton_clicked)

        self.clearSelectionButton = QtWidgets.QPushButton('Clear Selection')
        self.clearSelectionButton.setObjectName('clearSelectionButton')
        self.clearSelectionButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.clearSelectionButton.setFixedHeight(24)
        self.clearSelectionButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.clearSelectionButton.setToolTip('Removes all tree items.')
        self.clearSelectionButton.clicked.connect(self.on_clearSelectionPushButton_clicked)

        self.selectionDivider = QtWidgets.QFrame()
        self.selectionDivider.setObjectName('selectionDivider')
        self.selectionDivider.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.selectionDivider.setFrameShape(QtWidgets.QFrame.HLine)
        self.selectionDivider.setFrameShadow(QtWidgets.QFrame.Sunken)

        self.simulatePushButton = QtWidgets.QPushButton('Simulate')
        self.simulatePushButton.setObjectName('simulatePushButton')
        self.simulatePushButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.simulatePushButton.setFixedHeight(30)
        self.simulatePushButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.simulatePushButton.setStyleSheet('QPushButton:hover:checked { background-color: green; }\nQPushButton:checked { background-color: darkgreen; border: none; }')
        self.simulatePushButton.setCheckable(True)
        self.simulatePushButton.toggled.connect(self.on_simulatePushButton_toggled)

        self.selectionLayout.addWidget(self.selectionTreeWidget, 0, 0, 1, 2)
        self.selectionLayout.addWidget(self.addSelectionPushButton, 1, 0)
        self.selectionLayout.addWidget(self.removeSelectionButton, 1, 1)
        self.selectionLayout.addWidget(self.appendSelectionPushButton, 2, 0)
        self.selectionLayout.addWidget(self.clearSelectionButton, 2, 1)
        self.selectionLayout.addWidget(self.selectionDivider, 3, 0, 1, 2)
        self.selectionLayout.addWidget(self.simulatePushButton, 4, 0, 1, 2)

        centralLayout.addWidget(self.selectionGroupBox)

        # Initialize presets widget
        #
        self.presetsLayout = QtWidgets.QHBoxLayout()
        self.presetsLayout.setObjectName('presetsLayout')
        self.presetsLayout.setContentsMargins(0, 0, 0, 0)

        self.presetsLabel = QtWidgets.QLabel('Presets:')
        self.presetsLabel.setObjectName('presetsLabel')
        self.presetsLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.presetsLabel.setFixedSize(QtCore.QSize(64, 24))
        self.presetsLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.presetsComboBox = QtWidgets.QComboBox()
        self.presetsComboBox.setObjectName('presetsComboBox')
        self.presetsComboBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.presetsComboBox.setFixedHeight(24)
        self.presetsComboBox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.presetsComboBox.currentTextChanged.connect(self.on_presetsComboBox_currentTextChanged)

        self.createPresetPushButton = QtWidgets.QPushButton(QtGui.QIcon(':/dcc/icons/new_file.svg'), '')
        self.createPresetPushButton.setObjectName('createPresetPushButton')
        self.createPresetPushButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.createPresetPushButton.setFixedSize(QtCore.QSize(24, 24))
        self.createPresetPushButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.createPresetPushButton.setToolTip('Creates a preset from the current settings.')
        self.createPresetPushButton.clicked.connect(self.on_createPresetPushButton_clicked)

        self.deletePresetPushButton = QtWidgets.QPushButton(QtGui.QIcon(':/dcc/icons/delete.svg'), '')
        self.deletePresetPushButton.setObjectName('deletePresetPushButton')
        self.deletePresetPushButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.deletePresetPushButton.setFixedSize(QtCore.QSize(24, 24))
        self.deletePresetPushButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.deletePresetPushButton.setToolTip('Deletes the current preset.')
        self.deletePresetPushButton.clicked.connect(self.on_deletePresetPushButton_clicked)

        self.presetsLayout.addWidget(self.presetsLabel)
        self.presetsLayout.addWidget(self.presetsComboBox)
        self.presetsLayout.addWidget(self.createPresetPushButton)
        self.presetsLayout.addWidget(self.deletePresetPushButton)

        # Initialize property widget
        #
        self.propertyLayout = QtWidgets.QGridLayout()
        self.propertyLayout.setObjectName('propertyLayout')
        self.propertyLayout.setContentsMargins(0, 0, 0, 0)

        self.dampingLabel = QtWidgets.QLabel('Damping:')
        self.dampingLabel.setObjectName('dampingLabel')
        self.dampingLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.dampingLabel.setFixedSize(QtCore.QSize(64, 24))
        self.dampingLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.dampingLabel.setToolTip('Attenuated speed. The larger the value, the harder it is to accelerate.')

        self.dampingSpinBox = QtWidgets.QDoubleSpinBox()
        self.dampingSpinBox.setObjectName('dampingSpinBox')
        self.dampingSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.dampingSpinBox.setFixedHeight(24)
        self.dampingSpinBox.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.dampingSpinBox.setDecimals(2)
        self.dampingSpinBox.setMinimum(0.0)
        self.dampingSpinBox.setMaximum(1.0)
        self.dampingSpinBox.setSingleStep(0.1)
        self.dampingSpinBox.setValue(0.1)
        self.dampingSpinBox.setWhatsThis('damping')
        self.dampingSpinBox.valueChanged.connect(self.on_dampingSpinBox_valueChanged)
        
        self.elasticityLabel = QtWidgets.QLabel('Elasticity:')
        self.elasticityLabel.setObjectName('elasticityLabel')
        self.elasticityLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.elasticityLabel.setFixedSize(QtCore.QSize(64, 24))
        self.elasticityLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.elasticityLabel.setToolTip('Force to return to the original pose.')

        self.elasticitySpinBox = QtWidgets.QDoubleSpinBox()
        self.elasticitySpinBox.setObjectName('elasticitySpinBox')
        self.elasticitySpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.elasticitySpinBox.setFixedHeight(24)
        self.elasticitySpinBox.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.elasticitySpinBox.setDecimals(2)
        self.elasticitySpinBox.setMinimum(0.0)
        self.elasticitySpinBox.setMaximum(1000.0)
        self.elasticitySpinBox.setSingleStep(1.0)
        self.elasticitySpinBox.setValue(30.0)
        self.elasticitySpinBox.setWhatsThis('elasticity')
        self.elasticitySpinBox.valueChanged.connect(self.on_elasticitySpinBox_valueChanged)

        self.stiffnessLabel = QtWidgets.QLabel('Stiffness:')
        self.stiffnessLabel.setObjectName('stiffnessLabel')
        self.stiffnessLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.stiffnessLabel.setFixedSize(QtCore.QSize(64, 24))
        self.stiffnessLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.stiffnessLabel.setToolTip('Suppresses changes between frames. Setting to 1 will result in loss of motion.')

        self.stiffnessSpinBox = QtWidgets.QDoubleSpinBox()
        self.stiffnessSpinBox.setObjectName('stiffnessSpinBox')
        self.stiffnessSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.stiffnessSpinBox.setFixedHeight(24)
        self.stiffnessSpinBox.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.stiffnessSpinBox.setDecimals(2)
        self.stiffnessSpinBox.setMinimum(0.0)
        self.stiffnessSpinBox.setMaximum(1.0)
        self.stiffnessSpinBox.setSingleStep(1.0)
        self.stiffnessSpinBox.setValue(0.1)
        self.stiffnessSpinBox.setWhatsThis('stiffness')
        self.stiffnessSpinBox.valueChanged.connect(self.on_stiffnessSpinBox_valueChanged)

        self.massLabel = QtWidgets.QLabel('Mass:')
        self.massLabel.setObjectName('massLabel')
        self.massLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.massLabel.setFixedSize(QtCore.QSize(64, 24))
        self.massLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.massLabel.setToolTip('Affects the force to return to the original pose.')

        self.massSpinBox = QtWidgets.QDoubleSpinBox()
        self.massSpinBox.setObjectName('massSpinBox')
        self.massSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.massSpinBox.setFixedHeight(24)
        self.massSpinBox.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.massSpinBox.setDecimals(2)
        self.massSpinBox.setMinimum(0.01)
        self.massSpinBox.setMaximum(1000.0)
        self.massSpinBox.setSingleStep(1.0)
        self.massSpinBox.setValue(1.0)
        self.massSpinBox.setWhatsThis('mass')
        self.massSpinBox.valueChanged.connect(self.on_massSpinBox_valueChanged)

        self.iterationsLabel = QtWidgets.QLabel('Iterations:')
        self.iterationsLabel.setObjectName('iterationsLabel')
        self.iterationsLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.iterationsLabel.setFixedSize(QtCore.QSize(64, 24))
        self.iterationsLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.iterationsLabel.setToolTip('Higher values increase the accuracy of collisions. Recommended value is 3 to 5. 0 disables collisions.')

        self.iterationsSpinBox = QtWidgets.QSpinBox()
        self.iterationsSpinBox.setObjectName('iterationsSpinBox')
        self.iterationsSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.iterationsSpinBox.setFixedHeight(24)
        self.iterationsSpinBox.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.iterationsSpinBox.setMinimum(1)
        self.iterationsSpinBox.setMaximum(10)
        self.iterationsSpinBox.setValue(5)
        self.iterationsSpinBox.setWhatsThis('iterations')
        self.iterationsSpinBox.valueChanged.connect(self.on_iterationsSpinBox_valueChanged)
        
        self.resetTimeLabel = QtWidgets.QLabel('Reset Time:')
        self.resetTimeLabel.setObjectName('resetTimeLabel')
        self.resetTimeLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.resetTimeLabel.setFixedSize(QtCore.QSize(64, 24))
        self.resetTimeLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.resetTimeLabel.setToolTip('Start frame of the simulation. Dynamic bones are disabled when the current frame is equal to or less than this value.')

        self.resetTimeSpinBox = qtimespinbox.QTimeSpinBox()
        self.resetTimeSpinBox.setObjectName('resetTimeSpinBox')
        self.resetTimeSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.resetTimeSpinBox.setFixedHeight(24)
        self.resetTimeSpinBox.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.resetTimeSpinBox.setMinimum(-9999999)
        self.resetTimeSpinBox.setMaximum(9999999)
        self.resetTimeSpinBox.setDefaultType(qtimespinbox.QTimeSpinBox.DefaultType.START_TIME)
        self.resetTimeSpinBox.setValue(self.scene.startTime)
        self.resetTimeSpinBox.setWhatsThis('resetTime')
        self.resetTimeSpinBox.valueChanged.connect(self.on_resetTimeSpinBox_valueChanged)
        
        self.propertyLayout.addWidget(self.dampingLabel, 0, 0)
        self.propertyLayout.addWidget(self.dampingSpinBox, 0, 1)
        self.propertyLayout.addWidget(self.elasticityLabel, 1, 0)
        self.propertyLayout.addWidget(self.elasticitySpinBox, 1, 1)
        self.propertyLayout.addWidget(self.stiffnessLabel, 2, 0)
        self.propertyLayout.addWidget(self.stiffnessSpinBox, 2, 1)
        self.propertyLayout.addWidget(self.massLabel, 0, 2)
        self.propertyLayout.addWidget(self.massSpinBox, 0, 3)
        self.propertyLayout.addWidget(self.iterationsLabel, 1, 2)
        self.propertyLayout.addWidget(self.iterationsSpinBox, 1, 3)
        self.propertyLayout.addWidget(self.resetTimeLabel, 2, 2)
        self.propertyLayout.addWidget(self.resetTimeSpinBox, 2, 3)

        # Initialize gravity widget
        #
        self.gravityLayout = QtWidgets.QHBoxLayout()
        self.gravityLayout.setObjectName('gravityLayout')
        self.gravityLayout.setContentsMargins(0, 0, 0, 0)

        self.gravityLabel = QtWidgets.QLabel('Gravity:')
        self.gravityLabel.setObjectName('gravityLabel')
        self.gravityLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.gravityLabel.setFixedSize(QtCore.QSize(64, 24))
        self.gravityLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.gravityXSpinBox = QtWidgets.QDoubleSpinBox()
        self.gravityXSpinBox.setObjectName('gravityXSpinBox')
        self.gravityXSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.gravityXSpinBox.setFixedHeight(24)
        self.gravityXSpinBox.setDecimals(2)
        self.gravityXSpinBox.setMinimum(-9999)
        self.gravityXSpinBox.setMaximum(9999)
        self.gravityXSpinBox.setSingleStep(1.0)
        self.gravityXSpinBox.setValue(0.0)
        self.gravityXSpinBox.setWhatsThis('gravityX')
        self.gravityXSpinBox.valueChanged.connect(self.on_gravityXSpinBox_valueChanged)
        
        self.gravityYSpinBox = QtWidgets.QDoubleSpinBox()
        self.gravityYSpinBox.setObjectName('gravityYSpinBox')
        self.gravityYSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.gravityYSpinBox.setFixedHeight(24)
        self.gravityYSpinBox.setDecimals(2)
        self.gravityYSpinBox.setMinimum(-9999)
        self.gravityYSpinBox.setMaximum(9999)
        self.gravityYSpinBox.setSingleStep(1.0)
        self.gravityYSpinBox.setValue(0.0)
        self.gravityYSpinBox.setWhatsThis('gravityY')
        self.gravityYSpinBox.valueChanged.connect(self.on_gravityYSpinBox_valueChanged)
        
        self.gravityZSpinBox = QtWidgets.QDoubleSpinBox()
        self.gravityZSpinBox.setObjectName('gravityZSpinBox')
        self.gravityZSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.gravityZSpinBox.setFixedHeight(24)
        self.gravityZSpinBox.setDecimals(2)
        self.gravityZSpinBox.setMinimum(-9999)
        self.gravityZSpinBox.setMaximum(9999)
        self.gravityZSpinBox.setSingleStep(1.0)
        self.gravityZSpinBox.setValue(1.0)
        self.gravityZSpinBox.setWhatsThis('gravityZ')
        self.gravityZSpinBox.valueChanged.connect(self.on_gravityZSpinBox_valueChanged)

        self.gravityMultiplierLabel = QtWidgets.QLabel('x')
        self.gravityMultiplierLabel.setObjectName('gravityMultiplierLabel')
        self.gravityMultiplierLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.gravityMultiplierLabel.setFixedSize(QtCore.QSize(8, 24))
        self.gravityMultiplierLabel.setAlignment(QtCore.Qt.AlignCenter)

        self.gravityMultiplierSpinBox = QtWidgets.QDoubleSpinBox()
        self.gravityMultiplierSpinBox.setObjectName('gravityMultiplierSpinBox')
        self.gravityMultiplierSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.gravityMultiplierSpinBox.setFixedHeight(24)
        self.gravityMultiplierSpinBox.setDecimals(2)
        self.gravityMultiplierSpinBox.setMinimum(0.0)
        self.gravityMultiplierSpinBox.setMaximum(1.0)
        self.gravityMultiplierSpinBox.setSingleStep(0.1)
        self.gravityMultiplierSpinBox.setValue(1.0)
        self.gravityMultiplierSpinBox.setWhatsThis('gravityMultiply')
        self.gravityMultiplierSpinBox.setToolTip('Multiplies the gravity vector by this amount.')
        self.gravityMultiplierSpinBox.valueChanged.connect(self.on_gravityMultiplierSpinBox_valueChanged)

        self.gravityLayout.addWidget(self.gravityLabel)
        self.gravityLayout.addWidget(self.gravityXSpinBox)
        self.gravityLayout.addWidget(self.gravityYSpinBox)
        self.gravityLayout.addWidget(self.gravityZSpinBox)
        self.gravityLayout.addWidget(self.gravityMultiplierLabel)
        self.gravityLayout.addWidget(self.gravityMultiplierSpinBox)

        # Initialize angle-limit widget
        #
        self.angleLimitLayout = QtWidgets.QHBoxLayout()
        self.angleLimitLayout.setObjectName('angleLimitLayout')
        self.angleLimitLayout.setContentsMargins(0, 0, 0, 0)

        self.angleLimitLabel = QtWidgets.QLabel('Angle Limit:')
        self.angleLimitLabel.setObjectName('angleLimitLabel')
        self.angleLimitLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.angleLimitLabel.setFixedSize(QtCore.QSize(64, 24))
        self.angleLimitLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.angleLimitLabel.setToolTip('Limits the rotation angles of the dynamic bones.')

        self.angleLimitSpinBox = QtWidgets.QDoubleSpinBox()
        self.angleLimitSpinBox.setObjectName('angleLimitSpinBox')
        self.angleLimitSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.angleLimitSpinBox.setFixedHeight(24)
        self.angleLimitSpinBox.setDecimals(2)
        self.angleLimitSpinBox.setMinimum(0.0)
        self.angleLimitSpinBox.setMaximum(360.0)
        self.angleLimitSpinBox.setSingleStep(1.0)
        self.angleLimitSpinBox.setValue(60.0)
        self.angleLimitSpinBox.setWhatsThis('angleLimit')
        self.angleLimitSpinBox.setEnabled(False)
        self.angleLimitSpinBox.valueChanged.connect(self.on_angleLimitSpinBox_valueChanged)

        self.angleLimitCheckBox = QtWidgets.QCheckBox('')
        self.angleLimitCheckBox.setObjectName('angleLimitCheckBox')
        self.angleLimitCheckBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.angleLimitCheckBox.setFixedHeight(24)
        self.angleLimitCheckBox.setWhatsThis('enableAngleLimit')
        self.angleLimitCheckBox.setToolTip('Toggles the angle limit.')
        self.angleLimitCheckBox.stateChanged.connect(self.on_angleLimitCheckBox_stateChanged)

        self.followRestPoseCheckBox = QtWidgets.QCheckBox('Follow Rest Pose')
        self.followRestPoseCheckBox.setObjectName('followRestPoseCheckBox')
        self.followRestPoseCheckBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.followRestPoseCheckBox.setFixedHeight(24)
        self.followRestPoseCheckBox.setToolTip('When checked, the simulation follows the animated pose.')
        self.followRestPoseCheckBox.stateChanged.connect(self.on_followRestPoseCheckBox_clicked)
        
        self.angleLimitLayout.addWidget(self.angleLimitLabel)
        self.angleLimitLayout.addWidget(self.angleLimitCheckBox)
        self.angleLimitLayout.addWidget(self.angleLimitSpinBox)
        self.angleLimitLayout.addWidget(self.followRestPoseCheckBox)

        # Initialize ground widget
        #
        self.groundLayout = QtWidgets.QHBoxLayout()
        self.groundLayout.setObjectName('groundLayout')
        self.groundLayout.setContentsMargins(0, 0, 0, 0)

        self.groundLabel = QtWidgets.QLabel('Ground:')
        self.groundLabel.setObjectName('groundLabel')
        self.groundLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.groundLabel.setFixedHeight(24)
        self.groundLabel.setFixedWidth(64)
        self.groundLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.groundCheckBox = QtWidgets.QCheckBox('')
        self.groundCheckBox.setObjectName('groundCheckBox')
        self.groundCheckBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.groundCheckBox.setFixedHeight(24)
        self.groundCheckBox.setToolTip('Toggles the ground collision mesh.')
        self.groundCheckBox.clicked.connect(self.on_groundCheckBox_clicked)

        self.groundLineEdit = QtWidgets.QLineEdit('')
        self.groundLineEdit.setObjectName('groundLineEdit')
        self.groundLineEdit.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.groundLineEdit.setFixedHeight(24)
        self.groundLineEdit.setReadOnly(True)

        self.groundPushButton = QtWidgets.QPushButton(QtGui.QIcon(':/dcc/icons/select.png'), '')
        self.groundPushButton.setObjectName('groundPushButton')
        self.groundPushButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.groundPushButton.setFixedSize(QtCore.QSize(24, 24))
        self.groundPushButton.clicked.connect(self.on_groundPushButton_clicked)

        self.groundLayout.addWidget(self.groundLabel)
        self.groundLayout.addWidget(self.groundCheckBox)
        self.groundLayout.addWidget(self.groundLineEdit)
        self.groundLayout.addWidget(self.groundPushButton)

        # Initialize properties group-box
        #
        self.propertiesLayout = QtWidgets.QVBoxLayout()
        self.propertiesLayout.setObjectName('propertiesLayout')

        self.propertiesGroupBox = QtWidgets.QGroupBox('Properties:')
        self.propertiesGroupBox.setObjectName('propertiesGroupBox')
        self.propertiesGroupBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.propertiesGroupBox.setLayout(self.propertiesLayout)
        
        self.presetsDivider = QtWidgets.QFrame()
        self.presetsDivider.setObjectName('presetsDivider')
        self.presetsDivider.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.presetsDivider.setFrameShape(QtWidgets.QFrame.HLine)
        self.presetsDivider.setFrameShadow(QtWidgets.QFrame.Sunken)

        self.propertyDivider = QtWidgets.QFrame()
        self.propertyDivider.setObjectName('propertyDivider')
        self.propertyDivider.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.propertyDivider.setFrameShape(QtWidgets.QFrame.HLine)
        self.propertyDivider.setFrameShadow(QtWidgets.QFrame.Sunken)

        self.gravityDivider = QtWidgets.QFrame()
        self.gravityDivider.setObjectName('gravityDivider')
        self.gravityDivider.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.gravityDivider.setFrameShape(QtWidgets.QFrame.HLine)
        self.gravityDivider.setFrameShadow(QtWidgets.QFrame.Sunken)

        self.angleLimitDivider = QtWidgets.QFrame()
        self.angleLimitDivider.setObjectName('angleLimitDivider')
        self.angleLimitDivider.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.angleLimitDivider.setFrameShape(QtWidgets.QFrame.HLine)
        self.angleLimitDivider.setFrameShadow(QtWidgets.QFrame.Sunken)

        self.propertiesLayout.addLayout(self.presetsLayout)
        self.propertiesLayout.addWidget(self.presetsDivider)
        self.propertiesLayout.addLayout(self.propertyLayout)
        self.propertiesLayout.addWidget(self.propertyDivider)
        self.propertiesLayout.addLayout(self.gravityLayout)
        self.propertiesLayout.addWidget(self.gravityDivider)
        self.propertiesLayout.addLayout(self.angleLimitLayout)
        self.propertiesLayout.addWidget(self.angleLimitDivider)
        self.propertiesLayout.addLayout(self.groundLayout)

        self.overlapPropertyWidgets = [
            self.dampingSpinBox,
            self.elasticitySpinBox,
            self.stiffnessSpinBox,
            self.massSpinBox,
            self.iterationsSpinBox,
            self.resetTimeSpinBox,
            self.gravityXSpinBox,
            self.gravityYSpinBox,
            self.gravityZSpinBox,
            self.gravityMultiplierSpinBox,
            self.angleLimitSpinBox,
            self.angleLimitCheckBox
        ]

        centralLayout.addWidget(self.propertiesGroupBox)

        # Initialize bake method widget
        #
        self.bakeMethodLayout = QtWidgets.QHBoxLayout()
        self.bakeMethodLayout.setObjectName('bakeMethodLayout')
        self.bakeMethodLayout.setContentsMargins(0, 0, 0, 0)

        self.positionRadioButton = QtWidgets.QRadioButton('Position')
        self.positionRadioButton.setObjectName('positionRadioButton')
        self.positionRadioButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.positionRadioButton.setFixedHeight(24)
        self.positionRadioButton.setFocusPolicy(QtCore.Qt.NoFocus)
        
        self.rotationRadioButton = QtWidgets.QRadioButton('Rotation')
        self.rotationRadioButton.setObjectName('rotationRadioButton')
        self.rotationRadioButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed))
        self.rotationRadioButton.setFixedHeight(24)
        self.rotationRadioButton.setFocusPolicy(QtCore.Qt.NoFocus)

        self.radioButtonGroup = QtWidgets.QButtonGroup(self.bakeMethodLayout)
        self.radioButtonGroup.setObjectName('radioButtonGroup')
        self.radioButtonGroup.setExclusive(True)
        self.radioButtonGroup.addButton(self.positionRadioButton, id=0)
        self.radioButtonGroup.addButton(self.rotationRadioButton, id=1)
        
        self.bakeMethodLayout.addWidget(self.positionRadioButton, alignment=QtCore.Qt.AlignCenter)
        self.bakeMethodLayout.addWidget(self.rotationRadioButton, alignment=QtCore.Qt.AlignCenter)
        
        # Initialize bake range widget
        #
        self.bakeRangeLayout = QtWidgets.QHBoxLayout()
        self.bakeRangeLayout.setObjectName('bakeRangeLayout')
        self.bakeRangeLayout.setContentsMargins(0, 0, 0, 0)

        self.startTimeLabel = QtWidgets.QLabel('Start:')
        self.startTimeLabel.setObjectName('startTimeLabel')
        self.startTimeLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.startTimeLabel.setFixedSize(QtCore.QSize(32, 24))
        self.startTimeLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.startTimeLabel.setToolTip('The frame to start baking.')

        self.startTimeSpinBox = qtimespinbox.QTimeSpinBox()
        self.startTimeSpinBox.setObjectName('startTimeLabel')
        self.startTimeSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.startTimeSpinBox.setFixedHeight(24)
        self.startTimeSpinBox.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.startTimeSpinBox.setMinimum(-9999999)
        self.startTimeSpinBox.setMaximum(9999999)
        self.startTimeSpinBox.setDefaultType(qtimespinbox.QTimeSpinBox.DefaultType.START_TIME)
        self.startTimeSpinBox.setValue(self.scene.startTime)
        
        self.endTimeLabel = QtWidgets.QLabel('End:')
        self.endTimeLabel.setObjectName('endTimeLabel')
        self.endTimeLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.endTimeLabel.setFixedSize(QtCore.QSize(32, 24))
        self.endTimeLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.endTimeLabel.setToolTip('The end frame to bake to.')

        self.endTimeSpinBox = qtimespinbox.QTimeSpinBox()
        self.endTimeSpinBox.setObjectName('endTimeSpinBox')
        self.endTimeSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.endTimeSpinBox.setFixedHeight(24)
        self.endTimeSpinBox.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.endTimeSpinBox.setMinimum(-9999999)
        self.endTimeSpinBox.setMaximum(9999999)
        self.endTimeSpinBox.setDefaultType(qtimespinbox.QTimeSpinBox.DefaultType.END_TIME)
        self.endTimeSpinBox.setValue(self.scene.endTime)
        
        self.stepLabel = QtWidgets.QLabel('Step:')
        self.stepLabel.setObjectName('stepLabel')
        self.stepLabel.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.stepLabel.setFixedSize(QtCore.QSize(32, 24))
        self.stepLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.stepLabel.setToolTip('The frame interval to bake at.')

        self.stepSpinBox = QtWidgets.QSpinBox()
        self.stepSpinBox.setObjectName('stepSpinBox')
        self.stepSpinBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.stepSpinBox.setFixedHeight(24)
        self.stepSpinBox.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.stepSpinBox.setMinimum(1)
        self.stepSpinBox.setMaximum(100)
        self.stepSpinBox.setValue(1)

        self.bakeRangeLayout.addWidget(self.startTimeLabel)
        self.bakeRangeLayout.addWidget(self.startTimeSpinBox)
        self.bakeRangeLayout.addWidget(self.endTimeLabel)
        self.bakeRangeLayout.addWidget(self.endTimeSpinBox)
        self.bakeRangeLayout.addWidget(self.stepLabel)
        self.bakeRangeLayout.addWidget(self.stepSpinBox)

        # Initialize baking group-box
        #
        self.bakingLayout = QtWidgets.QVBoxLayout()
        self.bakingLayout.setObjectName('bakingLayout')

        self.bakingGroupBox = QtWidgets.QGroupBox('Baking:')
        self.bakingGroupBox.setObjectName('bakingGroupBox')
        self.bakingGroupBox.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.bakingGroupBox.setLayout(self.bakingLayout)
        
        self.bakeDivider = QtWidgets.QFrame()
        self.bakeDivider.setObjectName('bakeDivider')
        self.bakeDivider.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.bakeDivider.setFrameShape(QtWidgets.QFrame.VLine)
        self.bakeDivider.setFrameShadow(QtWidgets.QFrame.Sunken)

        self.bakePushButton = QtWidgets.QPushButton('Bake')
        self.bakePushButton.setObjectName('bakePushButton')
        self.bakePushButton.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))
        self.bakePushButton.setFixedHeight(30)
        self.bakePushButton.setFocusPolicy(QtCore.Qt.NoFocus)
        self.bakePushButton.setToolTip('Bakes the simulation to the associated controls.')
        self.bakePushButton.clicked.connect(self.on_bakePushButton_clicked)

        self.bakingLayout.addLayout(self.bakeMethodLayout)
        self.bakingLayout.addLayout(self.bakeRangeLayout)
        self.bakingLayout.addWidget(self.bakeDivider)
        self.bakingLayout.addWidget(self.bakePushButton)
        
        centralLayout.addWidget(self.bakingGroupBox)
    # endregion

    # region Properties
    @property
    def scene(self):
        """
        Returns the scene interface.

        :rtype: mpyscene.MPyScene
        """

        return self._scene()

    @property
    def selection(self):
        """
        Getter method that returns the current selection.

        :rtype: List[mpynode.MPyNode]
        """

        return self._selection

    @property
    def selectionCount(self):
        """
        Getter method that returns the current selection count.

        :rtype: int
        """

        return self._selectionCount

    @property
    def ground(self):
        """
        Getter method that returns the ground collision mesh.

        :rtype: mpynode.MPynode
        """

        return self._ground

    @property
    def gravity(self):
        """
        Getter method that returns the gravity vector.

        :rtype: Tuple[float, float, float]
        """

        return (
            self.gravityXSpinBox.value(),
            self.gravityYSpinBox.value(),
            self.gravityZSpinBox.value()
        )

    @gravity.setter
    def gravity(self, gravity):
        """
        Setter method that updates the gravity.

        :type gravity: Tuple[float, float, float]
        :rtype: None
        """

        defaultGravity = self.scene.upVector * -980.0
        gravity = gravity if not stringutils.isNullOrEmpty(gravity) else defaultGravity

        self.gravityXSpinBox.setValue(gravity[0])
        self.gravityYSpinBox.setValue(gravity[1])
        self.gravityZSpinBox.setValue(gravity[2])

    @property
    def gravityMultiplier(self):
        """
        Getter method that returns the gravity multiplier.

        :rtype: float
        """

        return self.gravityMultiplierSpinBox.value()

    @gravityMultiplier.setter
    def gravityMultiplier(self, gravityMultiplier):
        """
        Setter method that updates the gravity multiplier.

        :type gravityMultiplier: float
        :rtype: None
        """

        self.gravityMultiplierSpinBox.setValue(gravityMultiplier)

    @property
    def angleLimitEnabled(self):
        """
        Getter method that returns the angle limit enabled state.

        :rtype: bool
        """

        return self.angleLimitCheckBox.isChecked()

    @angleLimitEnabled.setter
    def angleLimitEnabled(self, angleLimitEnabled):
        """
        Setter method that updates the angle limit enabled state.

        :type angleLimitEnabled: bool
        :rtype: None
        """

        self.angleLimitCheckBox.setChecked(angleLimitEnabled)

    @property
    def angleLimit(self):
        """
        Getter method that returns the angle limit.

        :rtype: int
        """

        return self.angleLimitSpinBox.value()

    @angleLimit.setter
    def angleLimit(self, angleLimit):
        """
        Setter method that updates the angle limit.

        :type angleLimit: float
        :rtype: None
        """

        self.angleLimitSpinBox.setValue(angleLimit)

    @property
    def followRestPose(self):
        """
        Getter method that returns the follow rest-pose flag.

        :rtype: bool
        """

        return self.followRestPoseCheckBox.isChecked()

    @followRestPose.setter
    def followRestPose(self, followRestPose):
        """
        Setter method that updates the follow rest-pose flag.

        :type followRestPose: bool
        :rtype: None
        """

        self.followRestPoseCheckBox.setChecked(followRestPose)

    @property
    def bakeOption(self):
        """
        Getter method that returns the bake option.

        :rtype: int
        """

        return self.radioButtonGroup.checkedId()

    @bakeOption.setter
    def bakeOption(self, bakeOption):
        """
        Setter method that updates the bake option.

        :type bakeOption: int
        :rtype: None
        """

        self.radioButtonGroup.buttons()[bakeOption].setChecked(True)

    @property
    def startTime(self):
        """
        Getter method that returns the start time.

        :rtype: int
        """

        return self.startTimeSpinBox.value()

    @startTime.setter
    def startTime(self, startTime):
        """
        Setter method that updates the start time.

        :type startTime: int
        :rtype: None
        """

        self.startTimeSpinBox.setValue(startTime)

    @property
    def endTime(self):
        """
        Getter method that returns the end time.

        :rtype: int
        """

        return self.endTimeSpinBox.value()

    @endTime.setter
    def endTime(self, endTime):
        """
        Setter method that updates the end time.

        :type endTime: int
        :rtype: None
        """

        self.endTimeSpinBox.setValue(endTime)

    @property
    def step(self):
        """
        Getter method that returns the step interval.

        :rtype: int
        """

        return self.stepSpinBox.value()

    @step.setter
    def step(self, interval):
        """
        Setter method that updates the step interval.

        :type interval: int
        :rtype: None
        """

        self.stepSpinBox.setValue(interval)
    # endregion

    # region Callbacks
    def sceneChanged(self, *args, **kwargs):
        """
        Notifies all properties of a scene change.

        :key clientData: Any
        :rtype: None
        """

        self.simulatePushButton.setChecked(False)
        self.selectionTreeWidget.clear()
        self.invalidateSelection()

    def selectionChanged(self, *args, **kwargs):
        """
        Notifies all properties of a selection change.

        :key clientData: Any
        :rtype: None
        """

        self.invalidateSelection()
    # endregion

    # region Methods
    def addCallbacks(self):
        """
        Adds any callbacks required by this window.

        :rtype: None
        """

        # Add callbacks
        #
        hasCallbacks = len(self._callbackIds) > 0

        if not hasCallbacks:

            callbackId = om.MSceneMessage.addCallback(om.MSceneMessage.kAfterNew, onSceneChanged)
            self._callbackIds.append(callbackId)

            callbackId = om.MSceneMessage.addCallback(om.MSceneMessage.kAfterOpen, onSceneChanged)
            self._callbackIds.append(callbackId)

            callbackId = om.MEventMessage.addEventCallback('SelectionChanged', onSelectionChanged)
            self._callbackIds.append(callbackId)

    def removeCallbacks(self):
        """
        Removes any callbacks created by this window.

        :rtype: None
        """

        # Remove callbacks
        #
        hasCallbacks = len(self._callbackIds) > 0

        if hasCallbacks:

            om.MMessage.removeCallbacks(self._callbackIds)
            self._callbackIds.clear()

        # Removes all simulation nodes from the scene
        #
        self.removeGroundCollision()
        self.removeDynamics()

    def loadSettings(self, settings):
        """
        Loads the user settings.

        :type settings: QtCore.QSettings
        :rtype: None
        """

        # Call parent method
        #
        super(QWiggler, self).loadSettings(settings)

        # Load user preferences
        #
        self.gravity = json.loads(settings.value('editor/gravity', defaultValue='[]', type=str))
        self.gravityMultiplier = settings.value('editor/gravityMultiplier', defaultValue=1.0, type=float)
        self.angleLimitEnabled = settings.value('editor/angleLimitEnabled', defaultValue=0, type=int)
        self.angleLimit = settings.value('editor/angleLimit', defaultValue=60.0, type=float)
        self.followRestPose = settings.value('editor/followRestPose', defaultValue=1, type=int)
        self.bakeOption = settings.value('editor/bakeOption', defaultValue=0, type=int)
        self.step = settings.value('editor/step', defaultValue=0, type=int)

        self.setCurrentPreset(settings.value('editor/currentPreset', defaultValue='Default', type=str))
        self.loadPreset(json.loads(settings.value('editor/presetEdits', defaultValue='{}', type=str)))

    def saveSettings(self, settings):
        """
        Saves the user settings.

        :type settings: QtCore.QSettings
        :rtype: None
        """

        # Call parent method
        #
        super(QWiggler, self).saveSettings(settings)

        # Save user preferences
        #
        settings.setValue('editor/currentPreset', self.currentPreset())
        settings.setValue('editor/presetEdits', self.dumpPreset(asString=True))
        settings.setValue('editor/gravity', json.dumps(self.gravity))
        settings.setValue('editor/gravityMultiplier', self.gravityMultiplier)
        settings.setValue('editor/angleLimitEnabled', int(self.angleLimitEnabled))
        settings.setValue('editor/angleLimit', self.angleLimit)
        settings.setValue('editor/followRestPose', int(self.followRestPose))
        settings.setValue('editor/bakeOption', self.bakeOption)
        settings.setValue('editor/step', self.step)

    def loadPlugins(self):
        """
        Loads the required plugins.

        :rtype: None
        """

        # Iterate through required plugins
        #
        extension = pluginutils.getPluginExtension()

        for name in self.__plugins__:

            plugin = f'{name}.{extension}'
            isLoaded = mc.pluginInfo(plugin, query=True, loaded=True)

            if not isLoaded:

                log.info(f'Loading plugin: {plugin}')
                mc.loadPlugin(plugin)

    def invalidatePresets(self):
        """
        Refreshes the preset related widgets.

        :rtype: None
        """

        # Get preset files
        #
        filenames = os.listdir(self._presetsDirectory)
        numFilenames = len(filenames)

        if numFilenames > 1:

            index = filenames.index('Default.json')
            item = filenames.pop(index)
            filenames.insert(0, item)  # For ease of use lets make sure the default preset is at the top!

        # Load json data from presets directory
        #
        self._presets.clear()

        for filename in filenames:

            name, extension = os.path.splitext(filename)

            if extension != '.json':

                continue

            presetPath = os.path.join(self._presetsDirectory, filename)

            with open(presetPath, 'r') as jsonFile:

                self._presets[name] = json.load(jsonFile)

        # Repopulate combo box with presets
        #
        currentText = self.presetsComboBox.currentText()
        numItems = len(self._presets)

        with qsignalblocker.QSignalBlocker(self.presetsComboBox):

            self.presetsComboBox.clear()
            self.presetsComboBox.addItems(list(self._presets.keys()))

            index = self.presetsComboBox.findText(currentText)

            if index >= 0:

                self.presetsComboBox.setCurrentIndex(index)

            elif numItems > 0:

                self.presetsComboBox.setCurrentIndex(0)

            else:

                pass

    def invalidateSelection(self):
        """
        Refreshes the internal selection tracker.

        :rtype: None
        """

        # Update internal selection trackers
        #
        self._selection = self.scene.selection(apiType=om.MFn.kTransform)
        self._selectionCount = len(self._selection)

    def currentPreset(self):
        """
        Returns the current name.

        :type text: str
        :rtype: None
        """

        return self.presetsComboBox.currentText()

    def setCurrentPreset(self, text):
        """
        Updates the current preset.

        :type text: str
        :rtype: None
        """

        index = self.presetsComboBox.findText(text)
        textCount = self.presetsComboBox.count()

        if 0 <= index < textCount:

            self.presetsComboBox.setCurrentIndex(index)

    def dumpPreset(self, asString=False):
        """
        Dumps the current properties into a dictionary.

        :type asString: bool
        :rtype: Dict[str, Union[int, float]]
        """

        obj = {
            'damping': self.dampingSpinBox.value(),
            'elasticity': self.elasticitySpinBox.value(),
            'stiffness': self.stiffnessSpinBox.value(),
            'mass': self.massSpinBox.value(),
            'iterations': self.iterationsSpinBox.value()
        }

        if asString:

            return json.dumps(obj)

        else:

            return obj

    def loadPreset(self, preset):
        """
        Loads the settings from the supplied preset.

        :type preset: Dict[str, Union[int, float]]
        :rtype: None
        """

        damping = preset.get('damping', 0.1)
        elasticity = preset.get('elasticity', 30.0)
        stiffness = preset.get('stiffness', 0.0)
        mass = preset.get('mass', 1.0)
        iterations = preset.get('iterations', 5)

        self.dampingSpinBox.setValue(damping)
        self.elasticitySpinBox.setValue(elasticity)
        self.stiffnessSpinBox.setValue(stiffness)
        self.massSpinBox.setValue(mass)
        self.iterationsSpinBox.setValue(iterations)

    def walkTreeWidgetItems(self, *topLevelItems):
        """
        Returns a generator that iterates through the active tree widget item

        :type topLevelItems: Union[QtWidgets.QTreeWidgetItem, List[QtWidgets.QTreeWidgetItem]]
        :rtype: Iterator[QtWidgets.QTreeWidgetItem]
        """

        hasItems = len(topLevelItems) > 0
        items = [self.selectionTreeWidget.topLevelItem(i) for i in range(self.selectionTreeWidget.topLevelItemCount())] if not hasItems else topLevelItems

        queue = deque(items)

        while len(queue) > 0:

            treeWidgetItem = queue.popleft()
            yield treeWidgetItem

            queue.extendleft(reversed([treeWidgetItem.child(i) for i in range(treeWidgetItem.childCount())]))

    def iterComponents(self):
        """
        Returns a generator that yields the components from the tree widget.

        :rtype: Iterator[Tuple[mpynode.MPyNode, mpynode.MPyNode, mpynode.MPyNode]]
        """

        for treeWidgetItem in self.walkTreeWidgetItems():

            controlUUID = om.MUuid(treeWidgetItem.whatsThis(Column.CONTROL))
            control = mpynode.MPyNode(controlUUID) if controlUUID.valid() else None

            jointUUID = om.MUuid(treeWidgetItem.whatsThis(Column.JOINT))
            joint = mpynode.MPyNode(jointUUID) if jointUUID.valid() else None

            dynamicsUUID = om.MUuid(treeWidgetItem.whatsThis(Column.DYNAMICS))
            dynamics = mpynode.MPyNode(dynamicsUUID) if dynamicsUUID.valid() else None

            yield control, joint, dynamics

    def iterBoneDynamics(self):
        """
        Returns a generator that yields bone dynamic nodes from the tree widget.

        :rtype: Iterator[mpynode.MPyNode]
        """

        for (control, joint, dynamics) in self.iterComponents():

            if dynamics is not None:

                yield dynamics

            else:

                continue

    def iterBones(self):
        """
        Returns a generator that yields bones from the tree widget.

        :rtype: Iterator[Tuple[mpynode.MPyNode, mpynode.MPyNode]]
        """

        for boneDynamics in self.iterBoneDynamics():

            startJoint = mpynode.MPyNode(boneDynamics['boneTranslateX'].source().node())
            endJoint = mpynode.MPyNode(boneDynamics['endTranslateX'].source().node())

            if startJoint is not None and endJoint is not None:

                yield startJoint, endJoint

            else:

                continue

    def hasController(self, *controls):
        """
        Evaluates if the selection tree contains the supplied controls.

        :type controls: Union[mpynode.MPyNode, List[mpynode.MPyNode]]
        :rtype: bool
        """

        currentUuids = {treeWidgetItem.whatsThis(Column.CONTROL): True for treeWidgetItem in self.walkTreeWidgetItems()}
        exists = any([currentUuids.get(control.uuid(asString=True), False) for control in controls if isinstance(control, mpynode.MPyNode)])

        return exists

    def pullSimulationProperties(self):
        """
        Pulls the simulation properties from the bone dynamic nodes and updates the associated widgets.

        :rtype: None
        """

        # Collect bone dynamics nodes from scene
        #
        boneDynamics = list(self.iterBoneDynamics())
        numBoneDynamics = len(boneDynamics)

        if numBoneDynamics == 0:

            return  # Nothing to do here

        # Iterate through property widgets
        #
        for (i, widget) in enumerate(self.overlapPropertyWidgets):

            # Check if values are identical
            #
            values = list({boneDynamics.getAttr(widget.whatsThis()) for boneDynamics in boneDynamics})
            isIdentical = len(values) == 1

            if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):

                if isIdentical:

                    widget.setValue(values[0])

                else:

                    widget.lineEdit().setText('Mixed Values')

            elif isinstance(widget, QtWidgets.QCheckBox):

                if isIdentical:

                    widget.setChecked(values[0])

                else:

                    widget.setCheckState(QtCore.Qt.PartiallyChecked)

            else:

                continue

    @animate.Animate(state=False)
    def pushSimulationProperties(self, *widgets):
        """
        Pushes the simulation property associated with the supplied widgets to the bone dynamic nodes.
        If no widgets are supplied then all properties are updated!

        :type widgets: Union[QtWidgets.QWidget, List[QtWidgets.QWidget]]
        :rtype: None
        """

        # Iterate through bone dynamics nodes
        #
        widgets = self.overlapPropertyWidgets if stringutils.isNullOrEmpty(widgets) else widgets

        for boneDynamics in self.iterBoneDynamics():

            # Iterate through widgets
            #
            for widget in widgets:

                # Update attribute associated with widget
                #
                attribute = widget.whatsThis()

                if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):

                    boneDynamics.setAttr(attribute, widget.value())

                elif isinstance(widget, QtWidgets.QCheckBox):

                    boneDynamics.setAttr(attribute, widget.isChecked())

                else:

                    continue

    @undo.Undo(state=False)
    def addSelection(self, selectedItem=None):
        """
        Adds the active node selection to the selection tree widget.

        :type selectedItem: Union[QtWidgets.QTreeWidgetItem, None]
        :rtype: None
        """

        # Invalidates if currently selected items are already in the tree widget
        #
        hasController = self.hasController(*self._selection)

        if hasController:

            QtWidgets.QMessageBox.warning(self, 'Add Selection', 'Selected nodes have already been added!')
            return

        # Iterate through active selection
        #
        treeWidgetItems = [None] * self._selectionCount
        hasItemSelection = isinstance(selectedItem, QtWidgets.QTreeWidgetItem)

        for (i, control) in enumerate(self._selection):

            # Create tree widget item from selected control
            #
            treeWidgetItem = QtWidgets.QTreeWidgetItem()
            treeWidgetItem.setText(Column.CONTROL, control.name())
            treeWidgetItem.setIcon(Column.CONTROL, QtGui.QIcon(':/wiggler/icons/redCircle.png'))
            treeWidgetItem.setSizeHint(Column.CONTROL, QtCore.QSize(100, 24))
            treeWidgetItem.setWhatsThis(Column.CONTROL, control.uuid(asString=True))

            treeWidgetItems[i] = treeWidgetItem

            if i == 0:

                if hasItemSelection:

                    selectedItem.addChild(treeWidgetItem)

                else:

                    self.selectionTreeWidget.addTopLevelItem(treeWidgetItem)

            else:

                parentItem = treeWidgetItems[i - 1]
                parentItem.addChild(treeWidgetItem)

            treeWidgetItem.setExpanded(True)

        # Resize columns
        #
        self.selectionTreeWidget.resizeColumnToContents(0)

    @undo.Undo(state=False)
    def removeSelection(self, *treeWidgetItems):
        """
        Removes the selected items from the selection tree widget.

        :type treeWidgetItems: Union[QtWidgets.QTreeWidgetItem, List[QtWidgets.QTreeWidgetItem]]
        :rtype: None
        """

        # Take selected item from tree widget
        #
        treeWidgetItems = list(self.walkTreeWidgetItems()) if stringutils.isNullOrEmpty(treeWidgetItems) else treeWidgetItems
        self.removeDynamics(*treeWidgetItems)

        for treeWidgetItem in treeWidgetItems:

            parentItem = treeWidgetItem.parent()
            isTopLevelItem = parentItem is None

            if isTopLevelItem:

                index = self.selectionTreeWidget.indexOfTopLevelItem(treeWidgetItem)
                self.selectionTreeWidget.takeTopLevelItem(index)

            else:

                index = parentItem.indexOfChild(treeWidgetItem)
                parentItem.takeChild(index)

            del treeWidgetItem

    @undo.Undo(state=False)
    def addGroundCollision(self):
        """
        Adds a plane (ground) collision mesh and connects its world matrix to each bone dynamics node.

        :rtype: None
        """

        with animate.Animate(state=False):

            groundName = mc.polyPlane(name='groundPlane', subdivisionsX=1, subdivisionsY=1, width=1000, height=1000)[0]
            ground = mpynode.MPyNode(groundName)
            ground.setDoNotWrite(True)

            if self.scene.upAxis == 'z':

                ground.setAttr('rotateX', 90)
                ground.freezeTransform()

            for boneDynamicsNode in self.iterBoneDynamics():

                ground.connectPlugs(f'worldMatrix[{ground.instanceNumber()}]', boneDynamicsNode['infinitePlaneCollider[0].infinitePlaneColMatrix'], force=True)

            self._ground = ground
            self.groundLineEdit.setText(f'{groundName}')

    @undo.Undo(state=False)
    def removeGroundCollision(self):
        """
        Removes the plane (ground) collision mesh

        :rtype: None
        """

        # Check if ground collision exists
        #
        if self._ground is None:

            return

        # Reset internal tracker
        #
        if self._ground.isAlive():

            self._ground.delete()
            self._ground = None

            self.groundLineEdit.setText('')

        # Clear plane collider arrays
        #
        for boneDynamicsNode in self.iterBoneDynamics():

            plug = boneDynamicsNode['infinitePlaneCollider']
            indices = plug.getExistingArrayAttributeIndices()

            boneDynamicsNode.removePlugElements(plug, indices)

    @undo.Undo(state=False)
    def createBoneDynamics(self, startJoint, endJoint, control=None, ground=None):
        """
        Creates a `boneDynamicsNode` and assigns it to the supplied bone.

        :type startJoint: mpy.builtins.jointmixin.JointMixin
        :type endJoint: mpy.builtins.jointmixin.JointMixin
        :type control: mpy.builtins.transformmixin.TransformMixin
        :type ground: mpy.builtins.transformmixin.TransformMixin
        :rtype: mpynode.MPyNode
        """

        timeNode = mpynode.MPyNode('time1')

        boneDynamicsName = f':{self.__namespace__}:{startJoint.name()}Dynamics'
        boneDynamics = self.scene.createNode('boneDynamicsNode', name=boneDynamicsName)  # type: mpy.plugins.bonedynamicsnodemixin.BoneDynamicsNodeMixin
        boneDynamics.fps = sceneutils.getFPS()
        boneDynamics.resetTime = self.scene.startTime
        boneDynamics.gravity = self.scene.upVector * -980.0
        boneDynamics.gravityMultiply = 1.0
        boneDynamics.setDoNotWrite(True)
        boneDynamics.connectPlugs(timeNode['outTime'], 'time')
        boneDynamics.connectPlugs(startJoint['translate'], 'boneTranslate')
        boneDynamics.connectPlugs(startJoint['scale'], 'boneScale')
        boneDynamics.connectPlugs(startJoint['inverseScale'], 'boneInverseScale')
        boneDynamics.connectPlugs(startJoint[f'parentMatrix[{startJoint.instanceNumber()}]'], 'boneParentMatrix')
        boneDynamics.connectPlugs(startJoint[f'parentInverseMatrix[{startJoint.instanceNumber()}]'], 'boneParentInverseMatrix')
        boneDynamics.connectPlugs(startJoint['jointOrient'], 'boneJointOrient')
        boneDynamics.connectPlugs(endJoint['translate'], 'endTranslate')
        boneDynamics.connectPlugs(endJoint['scale'], 'endScale')
        boneDynamics.connectPlugs('outputRotate', startJoint['rotate'])

        followRestPoseEnabled = self.followRestPoseCheckBox.isChecked()

        if control is not None and followRestPoseEnabled:

            control.connectPlugs('rotate', boneDynamics['rotationOffset'], force=True)

        groundEnabled = self.groundCheckBox.isChecked()

        if ground is not None and groundEnabled:

            ground.connectPlugs(f'worldMatrix[{ground.instanceNumber()}]', boneDynamics['infinitePlaneCollider[0].infinitePlaneColMatrix'], force=True)

        return boneDynamics

    @undo.Undo(state=False)
    def addDynamics(self, **kwargs):
        """
        Creates the required nodes to simulate the active tree widget items.

        :rtype: None
        """

        # Temporarily disable auto-key
        # If left on we'll accidentally add unwanted keyframes!
        #
        with animate.Animate(state=False):

            # Check if simulation namespace exists
            # If not, create it to nest simulation nodes under!
            #
            hasNamespace = mc.namespace(exists=f':{self.__namespace__}')

            if not hasNamespace:

                mc.namespace(add=self.__namespace__, parent=':')

            # Walk through tree widget items
            # Ensure simulation joints exists for each control!
            #
            for treeWidgetItem in self.walkTreeWidgetItems():

                # Find control from tree widget item
                #
                controlUUID = om.MUuid(treeWidgetItem.whatsThis(Column.CONTROL))
                control = mpynode.MPyNode(controlUUID)

                if control is None:

                    log.error(f'Can no longer locate control: {treeWidgetItem.text(Column.CONTROL)}')
                    return

                # Check if joint already exists
                #
                jointUUID = om.MUuid(treeWidgetItem.whatsThis(Column.JOINT))
                hasJoint = jointUUID.valid()

                if hasJoint:

                    continue  # Our work here is done

                # Create joint from control
                #
                parentItem = treeWidgetItem.parent()
                isTopLevelItem = parentItem is None
                parentJoint = mpynode.MPyNode(om.MUuid(parentItem.whatsThis(Column.JOINT))) if not isTopLevelItem else None

                jointName = f':{self.__namespace__}:{control.name()}_bone'
                joint = self.scene.createNode('joint', name=jointName, parent=parentJoint)
                joint.setDoNotWrite(True)

                treeWidgetItem.setText(Column.JOINT, joint.name())
                treeWidgetItem.setWhatsThis(Column.JOINT, joint.uuid(asString=True))
                treeWidgetItem.setIcon(Column.CONTROL, QtGui.QIcon(':/wiggler/icons/greenCircle.png'))

                # Finally, update joint transform
                #
                if isTopLevelItem:

                    # Override offset-parent matrix
                    #
                    control.connectPlugs(f'parentMatrix[{control.instanceNumber()}]', joint['offsetParentMatrix'])

                else:

                    # Assign rest matrix
                    #
                    parentControl = mpynode.MPyNode(om.MUuid(parentItem.whatsThis(Column.CONTROL)))
                    restMatrix = control.parentMatrix() * parentControl.worldMatrix().inverse()

                    joint.setMatrix(restMatrix, skipScale=True)
                    joint.freezePivots(includeTranslate=False, includeRotate=True, includeScale=False)

            # Re-walk through tree widget items
            # This time, assign simulation nodes to each bone!
            #
            for treeWidgetItem in self.walkTreeWidgetItems():

                # Check if dynamics already exist
                #
                hasBoneDynamics = not stringutils.isNullOrEmpty(treeWidgetItem.whatsThis(Column.DYNAMICS))

                if hasBoneDynamics:

                    continue  # Our work here is done

                # Evaluate child count
                # If joint has no children then add a tip joint!
                #
                control = mpynode.MPyNode(om.MUuid(treeWidgetItem.whatsThis(Column.CONTROL)))
                startJoint = mpynode.MPyNode(om.MUuid(treeWidgetItem.whatsThis(Column.JOINT)))

                isTip = treeWidgetItem.childCount() == 0

                if isTip:

                    # Create end joint and create bone dynamics
                    #
                    endJointName = f':{self.__namespace__}:{control.name()}_boneTip'
                    endJoint = self.scene.createNode('joint', name=endJointName, parent=startJoint)
                    endJoint.drawStyle = 2
                    endJoint.setAttr('translate', startJoint.getAttr('translate'))
                    endJoint.setDoNotWrite(True)

                    treeWidgetItem.setText(Column.JOINT_TIP, endJoint.name())
                    treeWidgetItem.setWhatsThis(Column.JOINT_TIP, endJoint.uuid(asString=True))

                    boneDynamics = self.createBoneDynamics(startJoint, endJoint, control=control, ground=self._ground)

                    treeWidgetItem.setText(Column.DYNAMICS, boneDynamics.name())
                    treeWidgetItem.setWhatsThis(Column.DYNAMICS, boneDynamics.uuid(asString=True))

                else:

                    # Create bone dynamics from start and end joint
                    #
                    endJoint = mpynode.MPyNode(om.MUuid(treeWidgetItem.child(0).whatsThis(Column.JOINT)))

                    boneDynamics = self.createBoneDynamics(startJoint, endJoint, control=control, ground=self._ground)

                    treeWidgetItem.setText(Column.DYNAMICS, boneDynamics.name())
                    treeWidgetItem.setWhatsThis(Column.DYNAMICS, boneDynamics.uuid(asString=True))

            # Push properties to new dynamic nodes
            #
            self.resizeBones()
            self.pushSimulationProperties()

    @undo.Undo(state=False)
    def removeDynamics(self, *treeWidgetItems):
        """
        Removes the simulation nodes from the supplied tree widget items.
        If no items are supplied then all simulation nodes are removed from the scene!

        :type treeWidgetItems: Union[QtWidgets.QTreeWidgetItem, List[QtWidgets.QTreeWidgetItem]]
        :rtype: None
        """

        # Iterate through tree widget items
        #
        treeWidgetItems = list(self.walkTreeWidgetItems()) if stringutils.isNullOrEmpty(treeWidgetItems) else treeWidgetItems

        for treeWidgetItem in treeWidgetItems:

            # Check if dynamics exist
            #
            dynamicsUUID = om.MUuid(treeWidgetItem.whatsThis(Column.DYNAMICS))
            hasDynamics = dynamicsUUID.valid()

            if hasDynamics:

                boneDynamics = mpynode.MPyNode(dynamicsUUID)

                if boneDynamics is not None:

                    boneDynamics.delete()

                treeWidgetItem.setText(Column.DYNAMICS, '')
                treeWidgetItem.setWhatsThis(Column.DYNAMICS, '')

            # Check if tip joint exists
            #
            tipJointUUID = om.MUuid(treeWidgetItem.whatsThis(Column.JOINT_TIP))
            hasTipJoint = tipJointUUID.valid()

            if hasTipJoint:

                tipJoint = mpynode.MPyNode(tipJointUUID)

                if tipJoint is not None:

                    tipJoint.delete()

                treeWidgetItem.setText(Column.JOINT_TIP, '')
                treeWidgetItem.setWhatsThis(Column.JOINT_TIP, '')

            # Check if joint exists
            #
            jointUUID = om.MUuid(treeWidgetItem.whatsThis(Column.JOINT))
            hasJoint = jointUUID.valid()

            if hasJoint:

                joint = mpynode.MPyNode(jointUUID)

                if joint is not None:

                    joint.removeConstraints()
                    joint.delete()

                treeWidgetItem.setText(Column.JOINT, '')
                treeWidgetItem.setWhatsThis(Column.JOINT, '')

            # Update row icon
            #
            treeWidgetItem.setIcon(Column.CONTROL, QtGui.QIcon(':/wiggler/icons/redCircle.png'))

    @undo.Undo(state=False)
    def resizeBones(self):
        """
        Resizes the radius of all the active bones in the scene.

        :rtype: None
        """

        for (startJoint, endJoint) in self.iterBones():

            length = om.MVector(endJoint.getAttr('translate')).length()
            radius = length / 2.0

            startJoint.radius = radius

    @undo.Undo(state=False)
    def addRotationOffset(self):
        """
        Connects the control's rotation to the rotation offset on the bone dynamics nodes.

        :rtype: None
        """

        for (control, joint, dynamics) in self.iterComponents():

            if control is not None and dynamics is not None:

                control.connectPlugs('rotate', dynamics['rotationOffset'], force=True)

            else:

                continue

    @undo.Undo(state=False)
    def removeRotationOffset(self):
        """
        Disconnects the control's rotation from the rotation offset on the bone dynamics nodes.

        :rtype: None
        """

        for dynamics in self.iterBoneDynamics():

            plug = dynamics['rotationOffset']

            dynamics.breakConnections(plug, recursive=True)
            dynamics.resetAttr(plug)

    def bakeDynamics(self):
        """
        Bakes all controllers with bone dynamics node(s).

        :rtype: None
        """

        boneDynamics = list(self.iterBoneDynamics())
        numBoneDynamics = len(boneDynamics)

        if numBoneDynamics == 0:

            QtWidgets.QMessageBox.warning(self, 'Bake Dynamics', 'Scene contains no simulation nodes!')
            return

        # Build transform cache from simulated joints
        #
        cache = defaultdict(dict)

        for time in inclusiveRange(self.startTime, self.endTime, self.step):

            for treeWidgetItem in self.walkTreeWidgetItems():

                joint = mpynode.MPyNode(om.MUuid(treeWidgetItem.whatsThis(Column.JOINT)))
                uuid = treeWidgetItem.whatsThis(Column.CONTROL)

                cache[uuid][time] = joint.worldMatrix(time=time)

        # Remove dynamics from scene
        #
        self.removeDynamics()

        # Update controls from cached matrices
        #
        skipTranslate = not self.positionRadioButton.isChecked()
        skipRotate = not self.rotationRadioButton.isChecked()

        with animate.Animate(state=True), undo.Undo(name='Bake Simulation'):

            for time in inclusiveRange(self.startTime, self.endTime, self.step):

                self.scene.time = time

                for (uuid, matrices) in cache.items():

                    control = mpynode.MPyNode(om.MUuid(uuid))
                    control.setWorldMatrix(matrices[time], skipTranslate=skipTranslate, skipRotate=skipRotate, skipScale=True)

    # region Slots
    @QtCore.Slot(QtWidgets.QTreeWidgetItem, int)
    def on_selectionTreeWidget_itemClicked(self, treeWidgetItem, column):
        """
        Slot method for the `selectionTreeWidget` widget's 'itemPressed' signal.

        :type treeWidgetItem: QtWidgets.QTreeWidgetItem
        :type column: int
        :rtype: None
        """

        # Check if selection requires toggling
        #
        if treeWidgetItem is self._activeTreeWidgetItem and self._clearSelection:

            treeWidgetItem.setSelected(False)

        # Update internal trackers
        #
        self._activeTreeWidgetItem = treeWidgetItem
        self._clearSelection = treeWidgetItem.isSelected()

    @QtCore.Slot()
    def on_addSelectionPushButton_clicked(self):
        """
        Slot method for the `addSelectionButton` widget's 'clicked' signal.

        :rtype: None
        """

        self.addSelection()

    @QtCore.Slot()
    def on_appendSelectionPushButton_clicked(self):
        """
        Slot method for the `appendSelectionButton` widget's 'clicked' signal.

        :rtype: None
        """

        selectedItems = self.selectionTreeWidget.selectedItems()
        hasSelectedItem = len(selectedItems) == 1

        if hasSelectedItem:

            selectedItem = selectedItems[0]
            self.addSelection(selectedItem=selectedItem)

        else:

            QtWidgets.QMessageBox.warning(self, 'Append Selection', 'No tree item selected to append to!')

    @QtCore.Slot()
    def on_removeSelectionPushButton_clicked(self):
        """
        Slot method for the `removeSelectionButton` widget's 'clicked' signal.

        :rtype: None
        """

        # Evaluate item selection
        #
        selectedItems = self.selectionTreeWidget.selectedItems()
        numSelectedItems = len(selectedItems)

        if numSelectedItems > 0:

            treeWidgetItems = list(self.walkTreeWidgetItems(selectedItems[0]))
            self.removeSelection(*treeWidgetItems)

        else:

            QtWidgets.QMessageBox.warning(self, 'Remove Selection', 'No items selected to remove!')

        # Check if simulate button requires resetting
        #
        numTopLevelItems = self.selectionTreeWidget.topLevelItemCount()

        if numTopLevelItems == 0:

            self.simulatePushButton.setChecked(False)

    @QtCore.Slot()
    def on_clearSelectionPushButton_clicked(self):
        """
        Slot method for the `clearSelectionButton` widget's `clicked` signal.

        rtype: None
        """

        self.removeSelection()
        self.simulatePushButton.setChecked(False)

    @QtCore.Slot(bool)
    def on_simulatePushButton_toggled(self, checked):
        """
        Slot method for the 'simulatePushButton' widget's 'clicked' signal.

        :type checked: bool
        :rtype: None
        """

        # Redundancy check
        #
        sender = self.sender()  # type: QtWidgets.QPushButton
        topLevelItemCount = self.selectionTreeWidget.topLevelItemCount()

        hasTopLevelItems = topLevelItemCount > 0

        if hasTopLevelItems:

            # Evaluate checked state
            #
            if checked:

                self.addDynamics()
                sender.setText('Simulating')

            else:

                self.removeDynamics()
                sender.setText('Simulate')

        else:

            # Check if button requires unchecking
            #
            if checked:

                sender.setChecked(not checked)

    @QtCore.Slot(str)
    def on_presetsComboBox_currentTextChanged(self, text):
        """
        Slot method for the `presetsComboBox` widget's `currentTextChanged` signal.

        :type text: str
        :rtype: None
        """

        preset = self._presets.get(text, None)

        if isinstance(preset, dict):

            self.loadPreset(preset)

        else:

            log.debug(f'Unable to locate "{text}" preset!')

    @QtCore.Slot()
    def on_createPresetPushButton_clicked(self):
        """
        Slot method for the `createPresetPushButton` widget's `clicked` signal.

        :rtype: None
        """

        # Prompt user
        #
        presetName, response = QtWidgets.QInputDialog.getText(
            self,
            'Create New Preset',
            'Enter Name:',
            QtWidgets.QLineEdit.Normal
        )

        if not response:

            log.info('Operation aborted...')
            return

        # Check if name is unique
        # Be sure to slugify the name before processing!
        #
        presetName = stringutils.slugify(presetName)

        exists = presetName in self._presets
        isEmpty = stringutils.isNullOrEmpty(presetName)

        if exists or isEmpty:

            # Prompt user
            #
            response = QtWidgets.QMessageBox.warning(
                self,
                'Create New Preset',
                'The supplied name already exists!',
                QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel
            )

            if response == QtWidgets.QMessageBox.Ok:

                self.createPresetPushButton.click()

        else:

            # Save preset
            #
            presetPath = os.path.join(self._presetsDirectory, f'{presetName}.json')
            preset = self.dumpPreset()

            with open(presetPath, 'w+') as jsonFile:

                log.info(f'Creating preset: {presetPath}')
                json.dump(preset, jsonFile, indent=4)

            self.invalidatePresets()

    @QtCore.Slot()
    def on_deletePresetPushButton_clicked(self):
        """
        Slot method for the `deletePresetPushButton` widget's `clicked` signal.

        :rtype: None
        """

        # Redundancy check
        #
        presetName = self.presetsComboBox.currentText()
        presetPath = os.path.join(self._presetsDirectory, f'{presetName}.json')

        isDefault = presetName == 'Default'
        isLocked = pathutils.isReadOnly(presetPath)

        if isDefault or isLocked:

            QtWidgets.QMessageBox.warning(self, 'Delete Preset', 'Cannot delete locked preset!')
            return

        # Confirm user wants to delete preset
        #
        response = QtWidgets.QMessageBox.warning(
            self,
            'Delete Preset',
            'Are you sure you want to delete this preset?',
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel
        )

        if response == QtWidgets.QMessageBox.Ok:

            log.info(f'Removing preset: {presetPath}')
            os.remove(presetPath)

            self.invalidatePresets()

        else:

            log.info('Operation aborted...')

    @QtCore.Slot(float)
    def on_dampingSpinBox_valueChanged(self, value):
        """
        Slot method for the `dampingSpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(float)
    def on_elasticitySpinBox_valueChanged(self, value):
        """
        Slot method for the `elasticitySpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(float)
    def on_stiffnessSpinBox_valueChanged(self, value):
        """
        Slot method for the `stiffnessSpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(float)
    def on_massSpinBox_valueChanged(self, value):
        """
        Slot method for the `elasticitySpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(int)
    def on_iterationsSpinBox_valueChanged(self, value):
        """
        Slot method for the `iterationsSpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(int)
    def on_resetTimeSpinBox_valueChanged(self, value):
        """
        Slot method for the `resetTimeSpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(bool)
    def on_followRestPoseCheckBox_clicked(self, checked=False):
        """
        Slot method for the `followRestPoseCheckBox` widget's `clicked` signal.

        :type checked: bool
        :rtype: None
        """

        if checked:

            self.addRotationOffset()

        else:

            self.removeRotationOffset()

    @QtCore.Slot(float)
    def on_gravityXSpinBox_valueChanged(self, value):
        """
        Slot method for the `gravityXSpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(float)
    def on_gravityYSpinBox_valueChanged(self, value):
        """
        Slot method for the `gravityYSpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(float)
    def on_gravityZSpinBox_valueChanged(self, value):
        """
        Slot method for the `gravityZSpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(float)
    def on_gravityMultiplierSpinBox_valueChanged(self, value):
        """
        Slot method for the `gravityMultiplySpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(int)
    def on_angleLimitCheckBox_stateChanged(self, state):
        """
        Slot method for the `angleLimitCheckBox` widget's `checkStateChanged` signal.

        :type state: bool
        :rtype: None
        """

        self.angleLimitSpinBox.setEnabled(bool(state))
        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(float)
    def on_angleLimitSpinBox_valueChanged(self, value):
        """
        Slot method for the `angleLimitSpinBox` widget's `valueChanged` signal.

        :type value: float
        :rtype: None
        """

        self.pushSimulationProperties(self.sender())

    @QtCore.Slot(bool)
    def on_groundCheckBox_clicked(self, checked=False):
        """
        Slot method for the 'groundCheckBox' widget's 'checkStateChanged' signal.

        :type checked: bool
        :rtype: None
        """

        if checked:

            self.addGroundCollision()

        else:

            self.removeGroundCollision()

    @QtCore.Slot()
    def on_groundPushButton_clicked(self):
        """
        Slot method for the `groundPushButton` widget's `clicked` signal.

        :rtype: None
        """

        if self._ground is not None:

            self.scene.setSelection([self._ground])

    @QtCore.Slot()
    def on_bakePushButton_clicked(self):
        """
        Slot method for the `bakePushButton` widget's `clicked` signal.

        :rtype: None
        """

        self.bakeDynamics()
        self.simulatePushButton.setChecked(False)
        self.selectionTreeWidget.clear()
    # endregion

