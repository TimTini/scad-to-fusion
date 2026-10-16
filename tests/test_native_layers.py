import math
import unittest

from scad2fusion.native_layers import offset_cove_radius,translated_profile_suffix,sector_profile
from scad2fusion.native_runtime import Frame


class LayerFeatureRecognitionTests(unittest.TestCase):
    def test_offset_cove_checks_every_corresponding_vertex(self):
        rings=[]
        for i in range(9):
            angle=-math.pi/2+i*math.pi/16
            inset=5*(1-math.cos(angle))
            rings.append({'position':5+5*math.sin(angle),'points':[[10-inset,0],[10-inset,10],[0,10-inset]]})
        rings.append({'position':20,'points':rings[-1]['points']})
        plan={'all_rings':rings,'tail_extrusion':{'start_index':8}}
        self.assertAlmostEqual(offset_cove_radius(plan),5)
        self.assertAlmostEqual(offset_cove_radius(plan,Frame([[2,0,0],[0,2,0],[0,0,2]])),5)
        self.assertIsNone(offset_cove_radius(plan,Frame([[2,0,0],[0,1,0],[0,0,1]])))
        rings[4]['points'][1][0]+=.1
        self.assertIsNone(offset_cove_radius(plan))

    def test_translated_suffix_retains_profile_shape(self):
        rings=[{'position':i,'points':[[0,i],[1,i],[0,i+1]]} for i in range(6)]
        rings[0]['points'][1][0]=.5
        self.assertEqual(translated_profile_suffix({'all_rings':rings}),1)
        rings[4]['points'][1][0]=2
        self.assertIsNone(translated_profile_suffix({'all_rings':rings}))

    def test_sector_radius_changes_preserve_piecewise_revolve_profile(self):
        rings=[]
        for z,r in [(0,2),(4,2),(5,3)]:
            points=[[7,8]]+[[7+r*math.cos(i*math.pi/16),8+r*math.sin(i*math.pi/16)] for i in range(9)]
            rings.append({'position':z,'points':points})
        result=sector_profile({'all_rings':rings})
        self.assertAlmostEqual(result['sweep'],90)
        plan={'all_rings':rings,'axis':2}
        self.assertIsNone(sector_profile(plan,Frame([[2,0,0],[0,1,0],[0,0,1]])))
        self.assertEqual(result['points'],[[0,0],[2,0],[2,4],[3,5],[0,5]])
        rings[1]['points'][4][0]+=.1
        self.assertIsNone(sector_profile({'all_rings':rings}))
