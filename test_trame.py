import unittest
from fusion import reconcile,enrich
from test_fusion import fixture
from trame import *
class TrameTests(unittest.TestCase):
 def test_mapping_and_balance(self):
  f,p=fixture();rows,_,_=enrich(f,reconcile(f,p),mode='categories')
  out=template_rows(rows,piece_table(rows))
  self.assertEqual(list(out[0]),HEADERS)
  self.assertEqual(out[0]['Libellé de ligne'],'FACT-0')
  self.assertEqual(out[0]['Numéro de pièce'],'42')
  self.assertEqual(out[0]['Date'],'20260315')
  self.assertFalse(validate_template(out))
 def test_collisions_and_qualification(self):
  f,p=fixture();rows,_,_=enrich(f,reconcile(f,p),mode='categories')
  rows+= [dict(r,JournalCode='VT',EcritureNum='OTHER',IdentifiantLigneSource=r['IdentifiantLigneSource']+'B') for r in rows]
  pieces=piece_table(rows)
  self.assertIn('MULTIPLE_JOURNAL_CODE',validate_template(template_rows(rows,pieces))[0]['Problèmes'])
  self.assertFalse(validate_template(template_rows(rows,pieces,True)))
 def test_imbalance_not_silently_fixed(self):
  f,p=fixture();rows,_,_=enrich(f,reconcile(f,p),mode='categories');rows[0]['Debit']='101'
  self.assertEqual(validate_template(template_rows(rows,piece_table(rows)))[0]['Écart'],'1.00')
 def test_split_whole_piece_and_unique_ids(self):
  f,p=fixture();rows,_,_=enrich(f,reconcile(f,p),mode='categories')
  for r in rows:r['JournalCode']='HA'
  other=[dict(r,EcritureNum='OTHER',IdentifiantLigneSource=r['IdentifiantLigneSource']+'B') for r in rows]
  good,bad=split_exports(rows+other)
  self.assertFalse(bad)
  self.assertEqual(len({r['Numéro de pièce'] for r in good}),2)
  other[0]['Debit']='101'
  good,bad=split_exports(rows+other)
  self.assertEqual(len(good),2);self.assertEqual(len(bad),2)
  self.assertFalse(validate_template(good))
  self.assertIn('déséquilibrée',bad[0]['Motif de vérification'])
 def test_ambiguity_quarantines_whole_piece(self):
  f,p=fixture();rows,_,_=enrich(f,reconcile(f,p),mode='categories')
  for r in rows:r['JournalCode']='HA'
  rows[0]['StatutRapprochement']='À RAPPROCHER'
  good,bad=split_exports(rows)
  self.assertFalse(good);self.assertEqual(len(bad),2)
