# -*- coding:utf-8 -*-
"""
=============================================================================
Provide Material Studio markup file class which do operations on these files.
=============================================================================
Written by PytLab <shaozhengjiang@gmail.com>, August 2015
Updated by PytLab <shaozhengjiang@gmail.com>, October 2016
==============================================================

"""
from os import getcwd
import logging
import xml.etree.cElementTree as ET

import numpy as np

from vaspy import VasPy, LazyProperty
from vaspy.atomco import AtomCo
from vaspy.errors import UnmatchedDataShape
from vaspy.functions import str2list


class XsdFile(AtomCo):
    def __init__(self, filename):
        """
        Create a Material Studio *.xsd file class.

        Example:

        >>> a = XsdFile(filename='ts.xsd')

        Class attributes descriptions
        =======================================================================
          Attribute      Description
          ============  =======================================================
          filename       string, name of the file the direct coordiante data
                         stored in
          ntot           int, the number of total atom number
          atoms          list of strings, atom types
          natoms         list of tuples, same shape with atoms.
                         (atom name, atom number)
          atoms_num      list of int, atom number of atoms in atoms
          atom_names     list of string,
                         Value of attribute 'Name' in Atom3d tag.
          tf             np.array, T & F info for atoms, dtype=np.string
          data           np.array, coordinates of atoms, dtype=float64
          bases          np.array, basis vectors of space, dtype=np.float64
          ============  =======================================================
        """
        super(XsdFile, self).__init__(filename)

        # Set logger.
        self.__logger = logging.getLogger("vaspy.XsdFile")

        # Load data in xsd.
        self.load()

    def load(self):
        # get element tree
        tree = ET.ElementTree(file=self.filename)
        self.tree = tree

        # MS version info
        root = tree.getroot()
        ms_version = root.get('Version')
        if ms_version:
            self.ms_version = ms_version
        # add WrittenBy attr
        if 'WrittenBy' in root.attrib:
            root.set('WrittenBy', 'VASPy')
        else:
            root.attrib.setdefault('WrittenBy', 'VASPy')

        # atom info
        self.get_atom_info()

        # lattice parameters
        self.bases = self.get_bases()

        # info in Name property.
        self.get_name_info()

        return

    def get_bases(self):
        "get bases from SpaceGroup element"
        # lattice parameters
        bases = []
        for elem in self.tree.iter():
            if elem.tag == 'SpaceGroup':
                for attr in ['AVector', 'BVector', 'CVector']:
                    basis = elem.attrib[attr]  # string
                    basis = [float(i.strip()) for i in basis.split(',')]
                    bases.append(basis)
                break
        bases = np.array(bases)
        #set base constant as 1.0
        self.bases_const = 1.0

        return bases

    def get_atom_info(self):
        "获取和原子相关的信息, 直接进行属性赋值"
        # atom info
        atomco_dict = {}
        natoms_dict = {}
        atoms = []
        tf = []
        tf_dict = {}
        atom_names = []
        atom_name_dict = {}

        for elem in self.tree.iter('Atom3d'):
            if 'XYZ' in elem.attrib:

                # atom name and number
                atom = elem.attrib['Components']
                if atom not in natoms_dict:
                    natoms_dict.setdefault(atom, 1)
                    atoms.append(atom)
                else:
                    natoms_dict[atom] += 1

                # coordinates
                xyz = elem.attrib['XYZ']  # string
                coordinate = [float(i.strip()) for i in xyz.split(',')]
                if atom not in atomco_dict:
                    atomco_dict.setdefault(atom, [coordinate])
                else:
                    atomco_dict[atom].append(coordinate)

                # T&F info
                if 'RestrictedProperties' in elem.attrib:
                    tf_info = ['F', 'F', 'F']
                else:
                    tf_info = ['T', 'T', 'T']
                if atom not in tf_dict:
                    tf_dict.setdefault(atom, [tf_info])
                else:
                    tf_dict[atom].append(tf_info)

                # atom name
                atom_name = elem.attrib.get('Name')
                # Damn, sometimes tag has no Name attr,
                # so customize it
                # 有可能个别原子是从其他文件复制过来的原因
                if not atom_name:
                    atom_name = atom + '_custom'
                if atom not in atom_name_dict:
                    atom_name_dict.setdefault(atom, [atom_name])
                else:
                    atom_name_dict[atom].append(atom_name)

        atoms_num = [natoms_dict[atm] for atm in atoms]
        natoms = zip(atoms, atoms_num)

        coordinates = []
        for atom in atoms:  # sorted by atoms
            # combine all coordinates
            coordinates += atomco_dict[atom]
            # combine all tf info
            tf += tf_dict[atom]
            # combine all atom_names
            atom_names += atom_name_dict[atom]

        # set class attrs
        self.ntot = len(atom_names)
        self.atoms_num = atoms_num
        self.atoms = atoms
        self.natoms = natoms
        self.tf = np.array(tf)
        self.tf_dict = tf_dict
        self.atom_names = atom_names
        self.atom_names_dict = atom_name_dict
        self.data = np.array(coordinates)
        self.atomco_dict = atomco_dict

        return

    def get_name_info(self):
        """
        获取文件中能量，力等数据.
        """
        # Get info string.
        for elem in self.tree.iter("SymmetrySystem"):
            info = elem.attrib["Name"]
            break

        # Get thermo data.
        fieldnames = ["energy", "force", "magnetism", "path"]
        try:
            for key, value in zip(fieldnames, info.split()):
                if key != "path":
                    data = float(value.split(':')[-1].strip())
                else:
                    data = value.split(":")[-1].strip()
                setattr(self, key, data)
        except:
            # Set default values.
            self.force, self.energy, self.magnetism = 0.0, 0.0, 0.0

            msg = "No data info in Name property '{}'".format(info)
            self.__logger.warning(msg)
        finally:
            self.path = getcwd()

        return

    def update(self):
        """
        根据最新数据获取更新ElementTree内容
        """
        if self.ntot != len(self.data):
            raise UnmatchedDataShape(
                'length of data is not equal to atom number.')
        elif self.ntot != len(self.tf):
            raise UnmatchedDataShape(
                'length of tf is not equal to atom number.')
        elif self.ntot != len(self.atom_names):
            raise UnmatchedDataShape(
                'length of atom names is not equal to atom number.')

        # atoms info
        self.update_atoms()

        # space group
        self.update_bases()

        # Thermodynamic info.
        self.update_name()

        return

    def update_atoms(self):
        """
        更新ElementTree原子相关的值"
        update attribute values about atoms in element tree.
        """
        for atom in self.atoms:
            idx = 0  # index for coordinate
            for elem in self.tree.iter('Atom3d'):
                # xyz value
                if 'XYZ' in elem.attrib and elem.attrib['Components'] == atom:
                    xyz = self.atomco_dict[atom][idx]  # list of float
                    xyz = ','.join([str(v) for v in xyz])
                    elem.set('XYZ', xyz)
                    # TF value
                    tf = self.tf_dict[atom][idx]
                    tf = ','.join(tf)
                    if tf == 'F,F,F':
                        if 'RestrictedProperties' not in elem.attrib:
                            elem.attrib.setdefault('RestrictedProperties',
                                                   'FractionalXYZ')
                    elif tf == 'T,T,T':
                        if 'RestrictedProperties' in elem.attrib:
                            elem.attrib.pop('RestrictedProperties')
                    #atom name
                    elem.set('Name', self.atom_names_dict[atom][idx])
                    idx += 1

        return

    def update_name(self):
        """
        更新ElementTree中能量，力，作业路径等信息。
        """
        value = ""
        for key, attr in zip(['E', 'F', 'M'], ["energy", "force", "magnetism"]):
            data = getattr(self, attr)
            value += "{}:{} ".format(key, data)
        value = value.strip()

        # Get current path.
        path = getcwd()
        value = "{} {}:{}".format(value, "P", path)

        for elem in self.tree.iter("SymmetrySystem"):
            elem.set("Name", value)
            break

        return

    def update_bases(self):
        "update bases value in ElementTree"
        bases = self.bases.tolist()
        bases_str = []
        # float -> string
        for basis in bases:
            xyz = ','.join([str(v) for v in basis])  # vector string
            bases_str.append(xyz)
        for elem in self.tree.iter('SpaceGroup'):
            elem.set('AVector', bases_str[0])
            elem.set('BVector', bases_str[1])
            elem.set('CVector', bases_str[2])
            break

        return

    def modify_color(self, atom_number, color=(255, 117, 51)):
        '''
        Modify color of atom.

        Parameters
        ----------
        atom_number: int, number of atom(start from 1)
        color: tuple of int, RGB value of color

        Example
        -------
        >>> a.modify_color(99, color=(255, 255, 255))
        '''
        # get atom type and number of this type
        # [48, 48, 30, 14] -> [48, 96, 126, 140]
        atoms_num_sum = [sum(self.atoms_num[: i+1])
                         for i in range(len(self.atoms))]
        for idx, n in enumerate(atoms_num_sum):
            if atom_number <= n:
                atom_idx = idx
                break
        atom_type = self.atoms[atom_idx]
        type_atom_number = atom_number - atoms_num_sum[atom_idx-1]  # start from 1

        # go through tags to modify atom color
        color_attr = '%d,%d,%d, 255' % color
        i = 0  # atom number counter
        for elem in self.tree.iter('Atom3d'):
            if 'XYZ' in elem.attrib and elem.attrib['Components'] == atom_type:
                i += 1
                # locate tag
                if i == type_atom_number:
                    # modify color attribute
                    if 'Color' not in elem.attrib:
                        elem.attrib.setdefault('Color', color_attr)
                    else:
                        elem.set('Color', color_attr)
                    break
        return

    def tofile(self, filename='./new.xsd'):
        "XsdFile object to .xsd file."
        self.update()
        self.tree.write(filename)

        return


class ArcFile(VasPy):
    def __init__(self, filename):
        """
        Create a Material Studio *.arc file class.

        Example:

        >>> a = ArcFile("00-05.arc")

        Class attributes descriptions
        ================================================================
         Attribute         Description
         ===============  ==============================================
         filename          string, name of arc file.
         coords_iterator   generator, yield Cartisan coordinates in
                           numpy array.
         lengths           list of float, lengths of lattice axes.
         angles            list of float, angles of lattice axes.
        ================  ==============================================
        """
        super(ArcFile, self).__init__(filename)

        # Set logger.
        self.__logger = logging.getLogger("vaspy.ArcFile")

    @property
    def coords_iterator(self):
        """
        Return generator for Cartisan coordinates in arc file iteration.
        返回每个轨迹的所有原子的笛卡尔坐标
        """
        with open(self.filename, "r") as f:
            collecting = False
            coords = []
            for line in f:
                line = line.strip()
                if not collecting and line.startswith("PBC "):  # NOTE: Use "PBC " to tell "PBC=" apart
                    collecting = True
                elif collecting and line.startswith("end"):
                    collecting = False
                    yield np.array(coords)
                    coords = []
                # Collect coordinates data.
                elif collecting:
                    line_list = str2list(line)
                    coord = [float(c) for c in line_list[1: 4]]
                    coords.append(coord)

    @LazyProperty
    def lengths(self):
        """
        Lengths of axes of supercell.
        晶格基向量长度。
        """
        with open(self.filename, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("PBC "):
                    line_list = str2list(line)
                    return [float(l) for l in line_list[1: 4]]
        return None

    @LazyProperty
    def angles(self):
        """
        Angels of axes of supercell in Degrees.
        晶格基向量夹角(角度)。
        """
        with open(self.filename, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("PBC "):
                    line_list = str2list(line)
                    return [float(l) for l in line_list[4: 7]]
        return None

    @LazyProperty
    def elements(self):
        """
        Element name of all atom in lattice.
        晶格中的所有元素种类名称。
        """
        with open(self.filename, "r") as f:
            collecting = False
            elements = []
            for line in f:
                line = line.strip()
                if not collecting and line.startswith("PBC "):
                    collecting = True
                elif collecting and line.startswith("end"):
                    collecting = False
                    return elements
                # Collect coordinates data.
                elif collecting:
                    line_list = str2list(line)
                    element = line_list[0]
                    elements.append(element)


class XtdFile(XsdFile):
    def __init__(self, filename, arcname=None):
        """
        Create Material Studio *.xtd file class.

        Example:

        >>> a = XtdFile(filename='00-04.xtd', arcname="00-04.arc")

        Class attributes descriptions
        =======================================================================
          Attribute        Description
          ==============  =====================================================
          filename         string, name of *.xtd file.
          arcname          string, name of *.arc file.
          coords_iterator  generator, yield direct coordinates.
          =====================================================================

        """
        super(XtdFile, self).__init__(filename)

        if arcname is not None:
            self.arcfile = ArcFile(arcname)
        else:
            self.arcfile = None

    @property
    def coords_iterator(self):
        """
        Return generator which yields direct coordinates.
        返回生成器生成相对坐标矩阵。
        """
        if self.arcfile is None:
            raise ValueError("No ArcFile object in XtdFile.")

        for cart_coords in self.arcfile.coords_iterator:
           dir_coords = self.cart2dir(self.bases, cart_coords)
           yield np.array(dir_coords)

