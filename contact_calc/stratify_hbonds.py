############################################################################
# Copyright 2018 Anthony Ma & Stanford University                          #
#                                                                          #
# Licensed under the Apache License, Version 2.0 (the "License");          #
# you may not use this file except in compliance with the License.         #
# You may obtain a copy of the License at                                  #
#                                                                          #
#     http://www.apache.org/licenses/LICENSE-2.0                           #
#                                                                          #
# Unless required by applicable law or agreed to in writing, software      #
# distributed under the License is distributed on an "AS IS" BASIS,        #
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. #
# See the License for the specific language governing permissions and      #
# limitations under the License.                                           #
############################################################################

##############################################################################
# Imports
##############################################################################

from vmd import *
import itertools
from .contact_utils import *

__all__ = ["stratify_hbond_subtypes"]


##############################################################################
# Functions
##############################################################################


def residue_vs_water_hbonds(hbonds, solvent_resn):
    """
    Split hbonds into those involving residues only and those mediated by water.
    """
    residue_hbonds, water_hbonds = [], []
    for hbond in hbonds:
        frame_idx, atom1_label, atom2_label, itype = hbond
        if solvent_resn in atom1_label or solvent_resn in atom2_label:
            water_hbonds.append(hbond)
        else:
            residue_hbonds.append(hbond)

    return residue_hbonds, water_hbonds


def stratify_residue_hbonds(residue_hbonds):
    """
    Stratify residue to residue hbonds into those between sidechain-sidechain,
    sidechain-backbone, and backbone-backbone
    """
    backbone_atoms = ['N', 'O']
    hbss, hbsb, hbbb = [], [], []

    # Iterate through each residue hbond and bin into appropriate subtype
    for frame_idx, atom1_label, atom2_label, itype in residue_hbonds:
        atom1 = atom1_label.split(":")[3]
        atom2 = atom2_label.split(":")[3]

        if atom1 not in backbone_atoms and atom2 not in backbone_atoms:
            hbss.append([frame_idx, "hbss", atom1_label, atom2_label])

        if (atom1 not in backbone_atoms and atom2 in backbone_atoms) or \
                (atom1 in backbone_atoms and atom2 not in backbone_atoms):
            hbsb.append([frame_idx, "hbsb", atom1_label, atom2_label])

        if atom1 in backbone_atoms and atom2 in backbone_atoms:
            hbbb.append([frame_idx, "hbbb", atom1_label, atom2_label])

    return hbss, hbsb, hbbb


def stratify_water_bridge(water_hbonds, solvent_resn):
    """
    Infer direct water bridges between residues that both have hbond
    with the same water (ie res1 -- water -- res2)
    """
    frame_idx, water_to_residues, _ = calc_water_to_residues_map(water_hbonds, solvent_resn)
    water_bridges = set()
    # Infer direct water bridges
    for water in water_to_residues:
        protein_atoms = sorted(list(water_to_residues[water]))
        for res_atom_pair in itertools.combinations(protein_atoms, 2):
            res_atom1, res_atom2 = res_atom_pair
            if res_atom1 != res_atom2:
                water_bridges.add((frame_idx, "wb", res_atom1, res_atom2, water))

    wb = sorted([list(entry) for entry in water_bridges])
    return wb


def stratify_extended_water_bridge(water_hbonds, solvent_resn):
    """
    Infer extended water bridges between residues that form hbond with
    water molecules that also have hbond between them.
    (ie res1 -- water1 -- water2 -- res2)
    """
    frame_idx, water_to_residues, solvent_bridges = calc_water_to_residues_map(water_hbonds, solvent_resn)
    extended_water_bridges = set()
    for water1, water2 in solvent_bridges:
        if water1 not in water_to_residues or water2 not in water_to_residues:
            continue
        res_atom1_list, res_atom2_list = water_to_residues[water1], water_to_residues[water2]

        for atom1 in res_atom1_list:
            for atom2 in res_atom2_list:
                extended_water_bridges.add((frame_idx, "wb2", atom1, atom2, water1, water2))

    extended_water_bridges = sorted(list(extended_water_bridges))

    wb2 = []
    for frame_idx, atom1, water1, water2, atom2, itype in extended_water_bridges:
        wb2.append([frame_idx, atom1, water1, water2, atom2, itype])

    return wb2


def stratify_hbond_subtypes(hbonds, solvent_resn):
    """
    Stratify the full hbonds list into the following subtypes: sidechain-sidechain,
    sidechain-backbone, backbone-backbone, water-bridge, and extended water-bridge

    Parameters
    ----------
    hbonds: list, [[frame_idx, atom1_label, atom2_label, itype], ...]
        List of all hydrogen bond contacts in a single frame. itype = "hb"

    solvent_resn: string, default = TIP3
        Denotes the resname of solvent in simulation

    Returns
    -------
    hbond_subtypes: list, [[frame_idx, atom1_label, atom2_label, itype], ...]
        List of all hydrogen contacts with itype = "hbss", "hbsb", "hbbb", "wb", or "wb2"
        corresponding to sidechain-sidechain, sidechain-backbone, backbone-backbone,
        water bridge and extended water bridge respectively.
    """
    residue_hbonds, water_hbonds = residue_vs_water_hbonds(hbonds, solvent_resn)
    hbss, hbsb, hbbb = stratify_residue_hbonds(residue_hbonds)
    wb = stratify_water_bridge(water_hbonds, solvent_resn)
    wb2 = stratify_extended_water_bridge(water_hbonds, solvent_resn)
    hbonds = hbss + hbsb + hbbb + wb + wb2

    return hbonds
