"""Explicit export mappings, applied after reconciliation on unchanged sources."""
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from fusion import ConversionError


def mapping_tables(rows):
    journals={}; banks={}
    for r in rows:
        j=r['JournalCode']
        journals.setdefault(j,{'Journal source':j,'Code cible':j,'Libellé cible':r.get('JournalLib','')})
        if r['CompteNum'].startswith('512'):
            account=r['CompteNum']
            item=banks.setdefault(account,{'Compte source':account,'Journaux source':set(),'Compte cible':account,'Libellé cible':r['CompteLib']})
            item['Journaux source'].add(j)
    for item in banks.values():item['Journaux source']=', '.join(sorted(item['Journaux source']))
    return list(journals.values()),list(banks.values())


def apply_mappings(rows,journals,banks):
    jm={r['Journal source']:r for r in journals};bm={r['Compte source']:r for r in banks}
    for rule in journals:
        if not str(rule['Code cible']).strip():raise ConversionError('Le code journal cible ne peut pas être vide.')
    for rule in banks:
        if not re.fullmatch(r'512[0-9]*',str(rule['Compte cible'])):raise ConversionError('Le compte bancaire cible doit être numérique et commencer par 512.')
    out=[]
    for original in rows:
        r=dict(original)
        if r['JournalCode'] in jm:
            rule=jm[r['JournalCode']];r['JournalCode']=str(rule['Code cible']).strip();r['JournalLib']=str(rule['Libellé cible'])
        if r['CompteNum'] in bm:
            rule=bm[r['CompteNum']];r['CompteNum']=str(rule['Compte cible']);r['CompteLib']=str(rule['Libellé cible'])
        out.append(r)
    return out


def weight_issues(rows):
    groups=defaultdict(list)
    for i,r in enumerate(rows):
        if r['CategorieAnalytique']:groups[r['IdentifiantLigneSource'],r['FamilleAnalytique']].append(i)
    errors=[]
    for (ident,family),indices in groups.items():
        try:
            weights=[Decimal(rows[i]['PoidsAnalytique'].replace(',','.')) for i in indices]
            ok=bool(family.strip()) and all(w.is_finite() and 0<w<=1 for w in weights) and abs(sum(weights)-1)<=Decimal('.01')
        except (InvalidOperation,ValueError):ok=False
        if not ok:
            for i in indices:
                r=rows[i];errors.append({'Ligne export':i,'Identifiant':ident,'Famille':family,'Catégorie':r['CategorieAnalytique'],'Poids':r['PoidsAnalytique'],'Montant PNM':r['MontantAnalytiquePNM'],'Débit':r['Debit'],'Crédit':r['Credit']})
    return errors


def normalize_invalid_weights(rows):
    """Only called on explicit user choice; preserve accounting and PNM amounts."""
    out=[dict(r) for r in rows]
    groups=defaultdict(list)
    for issue in weight_issues(out):groups[issue['Identifiant'],issue['Famille']].append(issue['Ligne export'])
    for indices in groups.values():
        try:values=[Decimal(out[i]['PoidsAnalytique'].replace(',','.')) for i in indices]
        except InvalidOperation:continue
        if not all(v.is_finite() and v>0 for v in values):continue
        total=sum(values)
        weights=[(v/total).quantize(Decimal('.000000000001')) for v in values]
        weights[-1]=1-sum(weights[:-1])
        if not all(0<w<=1 for w in weights):continue
        for i,w in zip(indices,weights):
            out[i]['PoidsAnalytique']=format(w,'f').replace('.',',')
            out[i]['StatutRapprochement']+=' — POIDS RENORMALISÉ SUR DEMANDE'
    return out


def ambiguity_review(result):
    """Review all unresolved lines and their actual remaining PNM candidates."""
    f,p,_,_,unresolved=result
    fm={r['_line']:r for r in f};pm={r.line:r for r in p.records}
    summary=[];details={}
    for issue in sorted(unresolved,key=lambda x:x['Ligne FEC']):
        r=fm[issue['Ligne FEC']]
        ids=[int(x) for x in issue['Candidats PNM'].split(', ') if x]
        candidates=[pm[i] for i in ids]
        suffix=r['EcritureNum'].rsplit('_',1)[-1]
        refs=sorted({c.ref for c in candidates})
        reason=('Aucun candidat disponible.' if not candidates else
                'Le suffixe FEC ne correspond à aucune pièce PNM candidate.' if suffix not in refs else
                'Le suffixe existe, mais la pièce complète ou l’unicité du rapprochement ne sont pas confirmées.')
        summary.append({'Ligne FEC':r['_line'],'Date':r['_date'].strftime('%d/%m/%Y'),
            'Journal':r['JournalCode'],'Écriture FEC':r['EcritureNum'],'Pièce FEC':suffix,
            'Facture':r['PieceRef'],'Compte':r['CompAuxNum'] or r['CompteNum'],
            'Libellé':r['EcritureLib'],'Débit':r['Debit'],'Crédit':r['Credit'],
            'Candidats':len(ids),'Pièces PNM':' | '.join(refs),
            'Analytique possible':'Oui' if any(c.allocations for c in candidates) else 'Non','Motif':reason})
        detail=[]
        for c in candidates:
            for a in c.allocations or [None]:
                detail.append({'Ligne PNM':c.line,'Pièce PNM':c.ref,'Date':c.date.strftime('%d/%m/%Y'),
                    'Journal':c.journal,'Compte':c.account,'Auxiliaire':c.sub if c.kind=='X' else '',
                    'Libellé':c.label,'Montant signé':str(c.signed),'Plan':a.plan if a else '',
                    'Catégorie':a.sub if a else '', 'Montant analytique':str(a.signed) if a else ''})
        details[r['_line']]=detail
    return summary,details


def remap_reserved_clients(rows,extra_accounts=()):
    """Avoid Pennylane integration namespaces without merging distinct accounts."""
    accounts={r['CompteNum'] for r in rows}
    blocked={a for a in accounts if a.startswith(('41106','411900'))}
    blocked.update(a for a in extra_accounts if a in accounts and a.startswith('411'))
    occupied=set(accounts);mapping={}
    for old in sorted(blocked):
        base='4111'+old[3:] if old[3:].isascii() and old[3:].isdigit() else '4111000000'
        target=base;i=1
        while target in occupied:
            target=f'{base}{i:02d}';i+=1
        occupied.add(target);mapping[old]=target
    out=[dict(r,CompteNum=mapping.get(r['CompteNum'],r['CompteNum'])) for r in rows]
    labels={r['CompteNum']:r['CompteLib'] for r in rows}
    table=[{'Compte source':old,'Compte exporté':new,'Libellé':labels[old]} for old,new in mapping.items()]
    return out,table
