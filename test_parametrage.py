import unittest
from parametrage import *

class MappingTests(unittest.TestCase):
    def test_bank_all_journals_and_no_cascade(self):
        rows=[dict(JournalCode=j,JournalLib='Original',CompteNum=c,CompteLib='Bank',Debit='12,00',EcritureDate='20261028',EcritureLet='AA') for j,c in [('50','512400'),('JRRAN','512400'),('50','401ABC'),('51','512200')]]
        js,bs=mapping_tables(rows)
        js[0].update({'Code cible':'BNP','Libellé cible':'Banque BNP'})
        bs[0].update({'Compte cible':'512200','Libellé cible':'BNP cible'})
        bs[1].update({'Compte cible':'512900','Libellé cible':'CMB cible'})
        out=apply_mappings(rows,js,bs)
        self.assertEqual([r['CompteNum'] for r in out],['512200','512200','401ABC','512900'])
        self.assertEqual([r['JournalCode'] for r in out],['BNP','JRRAN','BNP','51'])
        for a,b in zip(rows,out):
            for k in ('Debit','EcritureDate','EcritureLet'):self.assertEqual(a[k],b[k])
        self.assertEqual(rows[0]['CompteNum'],'512400')

    def test_weight_validation_and_explicit_normalization(self):
        rows=[dict(IdentifiantLigneSource='X',FamilleAnalytique='Plan 1',CategorieAnalytique=c,PoidsAnalytique=w,MontantAnalytiquePNM='30',Debit='50',Credit='0',StatutRapprochement='SOURCE') for c,w in [('A','1,2'),('B','0,8')]]
        self.assertEqual(len(weight_issues(rows)),2)
        out=normalize_invalid_weights(rows)
        self.assertFalse(weight_issues(out))
        self.assertEqual(out[0]['PoidsAnalytique'],'0,600000000000')
        self.assertEqual(rows[0]['PoidsAnalytique'],'1,2')
        self.assertEqual(out[0]['Debit'],'50')
        rows[0]['PoidsAnalytique']='-1'
        self.assertTrue(weight_issues(normalize_invalid_weights(rows)))

class ReservedClientTests(unittest.TestCase):
    def test_reserved_mapping_consistent_and_collision_safe(self):
        rows=[dict(CompteNum=a,CompteLib='Client',Debit='10',EcritureLet='AA') for a in ['4110652','4110652','4119001','41110652','411123','4010652']]
        out,mapping=remap_reserved_clients(rows)
        self.assertEqual([r['CompteNum'] for r in out],['4111065201','4111065201','41119001','41110652','411123','4010652'])
        self.assertEqual(len(mapping),2)
        for a,b in zip(rows,out):
            for k in ['CompteLib','Debit','EcritureLet']:self.assertEqual(a[k],b[k])
        self.assertEqual(rows[0]['CompteNum'],'4110652')
        again,_=remap_reserved_clients(out)
        self.assertEqual(out,again)
    def test_simple_mapping(self):
        out,_=remap_reserved_clients([{'CompteNum':'4110652','CompteLib':'CLIENT'}])
        self.assertEqual(out[0]['CompteNum'],'41110652')
