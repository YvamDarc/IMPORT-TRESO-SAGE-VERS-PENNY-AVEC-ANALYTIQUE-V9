import unittest,csv,io
from fusion import *

def pnmline(ac='606100',n='100',kind=' ',sub='',ref='42',dt='150326',sid='1'):
    s=list(' '*199)
    for start,size,val in [(0,3,'60'),(3,6,dt),(9,2,'FF'),(11,13,ac),(24,1,kind),(25,13,sub),(38,13,ref),(51,25,'FACTURE TEST'),(83,1,'D' if D(n)>0 else 'C'),(84,20,str(abs(D(n)))),(104,1,'N'),(105,7,sid),(138,3,'EUR'),(164,10,'1' if kind=='A' else '')]:s[start:start+size]=val.ljust(size)
    return ''.join(s)
def fixture(duplicate=False):
    fields=['JournalCode','EcritureNum','EcritureDate','CompteNum','CompAuxNum','PieceRef','PieceDate','EcritureLib','Debit','Credit']
    rows=[];lines=[]
    for i in range(2 if duplicate else 1):
        rows.extend([['60',f'E{i}','20260315','606100','',f'FACT-{i}','20260310','FACTURE TEST','100','0'],['60',f'E{i}','20260315','401000','401TEST',f'FACT-{i}','20260310','FACTURE TEST','0','100']])
        lines.extend([pnmline(ref=str(42+i)),pnmline(kind='A',sub=f'VEHICULE{i}',ref=str(42+i)),pnmline(ac='401000',n='-100',kind='X',sub='401TEST',ref=str(42+i),sid='2')])
    out=io.StringIO();w=csv.writer(out,delimiter='\t');w.writerow(fields);w.writerows(rows)
    return out.getvalue().encode(),('DEMO\n'+'\n'.join(lines)).encode('cp850')
class Tests(unittest.TestCase):
    def test_suffix_resolves_identical_pieces(self):
        f,p=fixture(True)
        f=f.replace(b'E0',b'60_mars26_42').replace(b'E1',b'60_mars26_43')
        result=reconcile(f,p)
        self.assertFalse(result[4])
        out,_,_=enrich(f,result)
        self.assertEqual(out[0]['CategorieAnalytique'],'VEHICULE0')
        self.assertEqual(out[2]['CategorieAnalytique'],'VEHICULE1')
    def test_missing_suffix_match_keeps_ambiguity(self):
        f,p=fixture(True)
        f=f.replace(b'E0',b'60_mars26_90').replace(b'E1',b'60_mars26_91')
        self.assertEqual(len(reconcile(f,p)[4]),4)
    def test_competing_suffix_claims_not_arbitrary(self):
        f,p=fixture(True)
        f=f.replace(b'E0',b'60_mars26_42').replace(b'E1',b'60_autre26_42')
        self.assertEqual(len(reconcile(f,p)[4]),4)
    def test_other_original_cells_preserved(self):
        f,p=fixture();h,source=original_fec(f)
        rows,fields,report=enrich(f,reconcile(f,p))
        protected=[k for k in h if k not in ('CompteNum','CompteLib','CompAuxNum','CompAuxLib')]
        self.assertEqual([{k:r[k] for k in protected} for r in rows],[{k:r[k] for k in protected} for r in source])
        self.assertNotIn('CompAuxNum',fields)
        self.assertNotIn('CompAuxLib',fields)
        self.assertEqual(rows[1]['CompteNum'],'401TEST')
        self.assertEqual(rows[0]['JournalCode'],'60')
        self.assertEqual(rows[0]['EcritureDate'],'20260315')
        self.assertEqual(rows[0]['PieceRef'],'FACT-0')
        self.assertEqual(rows[0]['NumeroPieceComptablePNM'],'42')
    def test_auxiliary_code_and_label_take_precedence(self):
        rows=[{'CompteNum':'401000','CompteLib':'FOURNISSEURS','CompAuxNum':'40100123','CompAuxLib':'SOCIETE X','EcritureLib':'FACTURE'}]
        fields=collapse_accounts(rows,list(rows[0]))
        self.assertEqual(rows[0]['CompteNum'],'40100123')
        self.assertEqual(rows[0]['CompteLib'],'SOCIETE X')
        self.assertEqual(rows[0]['EcritureLib'],'FACTURE')
        self.assertNotIn('CompAuxNum',rows[0]);self.assertNotIn('CompAuxLib',fields)
    def test_general_account_and_missing_auxiliary_label(self):
        rows=[{'CompteNum':'606600','CompteLib':'CARBURANT','CompAuxNum':'  ','CompAuxLib':'UNUSED'},
              {'CompteNum':'401000','CompteLib':'FOURNISSEURS','CompAuxNum':'00123','CompAuxLib':''}]
        collapse_accounts(rows,list(rows[0]))
        self.assertEqual(rows[0]['CompteNum'],'606600');self.assertEqual(rows[0]['CompteLib'],'CARBURANT')
        self.assertEqual(rows[1]['CompteNum'],'00123');self.assertEqual(rows[1]['CompteLib'],'FOURNISSEURS')
    def test_lettering_labels_and_extra_columns(self):
        f,p=fixture();h,rows=original_fec(f)
        for r in rows:r.update(JournalLib=' ACHATS ORIGINAL ',EcritureLet='AA',DateLet='20260410',Custom='  0001  ')
        h+=['JournalLib','EcritureLet','DateLet','Custom'];raw=csv_bytes(rows,h)
        out,_,rep=enrich(raw,reconcile(raw,p))
        self.assertEqual(out[0]['JournalLib'],' ACHATS ORIGINAL ')
        self.assertEqual(out[0]['Custom'],'  0001  ')
        self.assertEqual(out[0]['DateLet'],'20260410')
        self.assertEqual(rep['lettered_rows'],2)
    def test_ambiguous_no_guessed_category(self):
        f,p=fixture(True);out,_,rep=enrich(f,reconcile(f,p))
        self.assertEqual(len(out),4)
        self.assertTrue(all(r['CategorieAnalytique']=='' for r in out))
        self.assertTrue(all(r['CandidatsPNM'] for r in out))
    def test_analytic_source_not_repaired(self):
        f,p=fixture();p=p.replace(b'100                 N',b'120                 N',1)
        with self.assertRaises(ConversionError):reconcile(f,p)
    def test_incompatible_manual(self):
        with self.assertRaises(ConversionError):reconcile(*fixture(),manual={'2':4})
    def test_multisections_preserve_line_count_default(self):
        f,p=fixture();lines=p.decode('cp850').splitlines()
        lines[2]=pnmline(kind='A',sub='VEH1',n='60')
        lines.insert(3,pnmline(kind='A',sub='VEH2',n='40'))
        p='\n'.join(lines).encode('cp850');res=reconcile(f,p)
        out,_,rep=enrich(f,res)
        self.assertEqual(len(out),2);self.assertEqual(out[0]['CategorieAnalytique'],'VEH1 | VEH2')
        expanded,_,_=enrich(f,res,mode='categories')
        self.assertEqual(len(expanded),3)
        self.assertEqual(expanded[0]['IdentifiantLigneSource'],expanded[1]['IdentifiantLigneSource'])
        self.assertEqual(expanded[0]['Debit'],'100')
if __name__=='__main__':unittest.main()
