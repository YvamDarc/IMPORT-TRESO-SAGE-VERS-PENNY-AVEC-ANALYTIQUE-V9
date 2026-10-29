"""Regression tests for old Streamlit sessions and old enrichment reports."""
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

APP=Path(__file__).with_name('app.py').read_text()
PREAMBLE='''
import streamlit as st
import fusion
from test_fusion import fixture
_test_f,_test_p=fixture()
class Upload:
 def __init__(self,data):self.data=data
 def getvalue(self):return self.data
def uploader(label,**kwargs):
 if label=='FEC initial':return Upload(_test_f)
 if label=='PNM avec analytique':return Upload(_test_p)
 return None
st.file_uploader=uploader
'''
class CacheTests(unittest.TestCase):
    def test_stale_session_recomputed_and_missing_key_repaired(self):
        a=AppTest.from_string(PREAMBLE+APP)
        a.session_state['export']=([],[],{'source_rows':2},b'old')
        a.session_state['export_key']=('legacy','Plan 1','Une ligne par ligne du FEC')
        a.run(timeout=30)
        self.assertFalse(a.exception)
        self.assertFalse(a.error)
        self.assertEqual(a.session_state['export'][2]['accounts_promoted'],1)
        rows,fields,report,content=a.session_state['export']
        report=dict(report);report.pop('accounts_promoted')
        a.session_state['export']=(rows,fields,report,content)
        # Even with a current cache key, an incomplete report forces regeneration.
        a.run(timeout=30)
        self.assertFalse(a.exception)
        self.assertEqual(a.session_state['export'][2]['accounts_promoted'],1)
        cached=a.session_state['export']
        a.run(timeout=30)
        self.assertIs(a.session_state['export'],cached)

    def test_old_engine_report_still_merges_real_accounts(self):
        legacy='''
_original_enrich=fusion.enrich
def legacy_enrich(raw,result,*args,**kwargs):
 rows,fields,report=_original_enrich(raw,result,*args,**kwargs)
 _,source=fusion.original_fec(raw)
 by_id={f'FEC-{r["_line"]:07d}':s for r,s in zip(result[0],source)}
 for row in rows:
  row.update({k:by_id[row['IdentifiantLigneSource']].get(k,'') for k in ['CompteNum','CompteLib','CompAuxNum','CompAuxLib']})
 for key in ['accounts_promoted','aux_labels_missing','output_base_columns']:report.pop(key,None)
 return rows,fields+['CompAuxNum','CompAuxLib'],report
fusion.enrich=legacy_enrich
'''
        a=AppTest.from_string(PREAMBLE+legacy+APP).run(timeout=30)
        self.assertFalse(a.exception)
        self.assertFalse(a.error)
        rows,fields,report,content=a.session_state['export']
        self.assertEqual(rows[1]['CompteNum'],'401TEST')
        self.assertNotIn('CompAuxNum',fields)
        self.assertNotIn(b'CompAuxNum',content.splitlines()[0])
        self.assertEqual(report['accounts_promoted'],1)
        self.assertEqual(len(a.get('download_button')),2)

if __name__=='__main__':unittest.main()
