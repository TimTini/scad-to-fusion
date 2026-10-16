"""Optional audit-extra integration: preserve multi-part component evidence."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import trimesh
except ImportError:
    trimesh = None

@unittest.skipIf(trimesh is None, 'requires audit extra')
class MeshAuditTests(unittest.TestCase):
    def test_two_part_model_matches_its_reference(self):
        spec = importlib.util.spec_from_file_location('mesh_audit', Path(__file__).parents[1] / 'tools/compare_meshes.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            first = trimesh.creation.box(extents=[20,20,10])
            first.apply_translation([0,0,5])
            second = first.copy()
            second.apply_translation([30,0,0])
            path = Path(directory) / 'parts.stl'
            trimesh.util.concatenate([first,second]).export(path)
            with patch('trimesh.proximity.closest_point',wraps=trimesh.proximity.closest_point) as query:
                result = module.compare(path,path,[(2,1.5)])
                self.assertLessEqual(max(len(call.args[1]) for call in query.call_args_list),256)
            self.assertEqual(result['status'],'passed')
            self.assertEqual(result['reference_components'],2)
            self.assertEqual(result['candidate_components'],2)
