import ast
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from snapshot_store import SnapshotRejected,publish_snapshot,publishing_lock

class SnapshotTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.output=Path(self.temp.name)/'orders.json'
  self.old=self.payload(10);self.output.write_text(json.dumps(self.old));self.bytes=self.output.read_bytes()
 def payload(self,n):return {'orders':[{'id':i} for i in range(n)],'products':[{'id':i} for i in range(n)],'count':n,'product_count':n,'errors':[]}
 def test_valid_snapshot_keeps_previous_copy(self):
  publish_snapshot(self.output,self.payload(11));self.assertEqual(json.loads(self.output.read_text())['count'],11);self.assertEqual(self.output.with_suffix('.json.last-good').read_bytes(),self.bytes)
 def test_partial_or_empty_or_shrunk_snapshot_cannot_replace_previous(self):
  for payload in [self.payload(0),self.payload(7),{**self.payload(10),'errors':[{'error':'offline'}]},{**self.payload(10),'count':999}]:
   with self.assertRaises(SnapshotRejected):publish_snapshot(self.output,payload)
   self.assertEqual(self.output.read_bytes(),self.bytes)
 def test_interrupted_publish_retains_complete_previous_bytes(self):
  import snapshot_store
  replace=snapshot_store.os.replace
  def interrupt(src,dest):
   if Path(dest)==self.output:raise OSError('simulated disk failure')
   return replace(src,dest)
  with patch('snapshot_store.os.replace',side_effect=interrupt):
   with self.assertRaises(OSError):publish_snapshot(self.output,self.payload(11))
  self.assertEqual(self.output.read_bytes(),self.bytes);self.assertEqual(list(self.output.parent.glob('.*.tmp')),[])
 def test_overlapping_collectors_are_rejected(self):
  with publishing_lock(self.output):
   with self.assertRaises(SnapshotRejected):
    with publishing_lock(self.output):self.fail('second collector entered')
 def test_actual_collector_partial_parse_does_not_publish(self):
  path=Path(__file__).resolve().parents[1]/'scripts/parse_orders.py';tree=ast.parse(path.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='collect_and_publish')
  folder=Path(self.temp.name)
  for i in range(10):(folder/f'fixture-{i}.xlsx').touch()
  def parse(p):return {'error':'unavailable'} if p.name!='fixture-0.xlsx' else {'file':p.name,'item_count':1,'date':'2026-09-11','items':[]}
  env={'FOLDER':folder,'OUT':self.output,'parse_workbook':parse,'dedupe_key':lambda x:x,'fetch_master_sheet':lambda:None,'aggregate_products':lambda x:[{'id':'fixture'}],'datetime':datetime,'sys':sys,'publish_snapshot':publish_snapshot}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'collector','exec'),env)
  with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SnapshotRejected):env['collect_and_publish']()
  self.assertEqual(self.output.read_bytes(),self.bytes)
if __name__=='__main__':unittest.main()
