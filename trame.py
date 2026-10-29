"""Pennylane template supplied by the user, plus the required analytic weight."""
from collections import defaultdict
from decimal import Decimal
from fusion import amount

HEADERS=['Date','Code Journal','Numéro de compte','Libellé de compte','Libellé de ligne','Taux de TVA du compte','Code pays du compte','Libellé de pièce','Numéro de pièce','Débit et/ou Crédit','Crédit','Famille de catégories','Catégorie','Identifiant de ligne','Identifiant de lettrage','Poids de la catégorie']

def piece_table(rows):
    groups=defaultdict(list)
    for r in rows:groups[r['EcritureNum'],r['JournalCode'],r['EcritureDate']].append(r)
    table=[]
    for (entry,journal,date),rs in groups.items():
        unique={r['IdentifiantLigneSource']:r for r in rs}
        refs=sorted({r['NumeroPieceComptablePNM'] for r in rs if r['NumeroPieceComptablePNM']})
        ref=refs[0] if len(refs)==1 else ''
        table.append({'Groupe source':str(len(table)+1),'Écriture FEC':entry,'Journal':journal,'Date':date,
            'Références PNM trouvées':' | '.join(refs),'Numéro de pièce':ref,
            'Libellé de pièce':next((r['EcritureLib'] for r in rs if r['EcritureLib'].strip()),entry),
            'Écart débit-crédit':format(sum((amount(r['Debit'])-amount(r['Credit']) for r in unique.values()),Decimal(0)),'.2f'),
            'Référence à vérifier':'Oui' if len(refs)!=1 or any(not r['NumeroPieceComptablePNM'] for r in rs) else 'Non'})
    return table

def template_rows(rows,pieces,qualify=False):
    lookup={(p['Écriture FEC'],p['Journal'],p['Date']):p for p in pieces}
    out=[];labels={}
    for r in rows:
        p=lookup[r['EcritureNum'],r['JournalCode'],r['EcritureDate']]
        ref=str(p['Numéro de pièce'] or '').strip()
        if qualify and ref:ref=f"{r['JournalCode']}-{r['EcritureDate']}-{ref}"
        label=labels.setdefault((ref,r['JournalCode'],r['EcritureDate']),p['Libellé de pièce'])
        out.append(dict(zip(HEADERS,[r['EcritureDate'],r['JournalCode'],r['CompteNum'],r['CompteLib'],r['PieceRef'],'','',
            label,ref,r['Debit'],r['Credit'],r['FamilleAnalytique'],r['CategorieAnalytique'],r['IdentifiantLigneSource'],r.get('EcritureLet',''),r['PoidsAnalytique']])))
    return out

def validate_template(rows):
    groups=defaultdict(list);issues=[]
    for r in rows:groups[r['Numéro de pièce']].append(r)
    for ref,rs in groups.items():
        reasons=[]
        if not ref:reasons.append('Numéro de pièce absent : référence PNM à renseigner')
        if len({r['Code Journal'] for r in rs})>1:reasons.append('MULTIPLE_JOURNAL_CODE')
        if len({r['Libellé de pièce'] for r in rs})>1:reasons.append('MULTIPLE_ENTRY_LABELS')
        if len({r['Date'] for r in rs})>1:reasons.append('Dates différentes pour un même numéro')
        unique={r['Identifiant de ligne']:r for r in rs}
        balance=sum((amount(r['Débit et/ou Crédit'])-amount(r['Crédit']) for r in unique.values()),Decimal(0))
        if balance:reasons.append('UNBALANCED_IMPORT')
        if reasons:issues.append({'Numéro de pièce':ref,'Lignes source':len(unique),'Écart':format(balance,'.2f'),'Problèmes':' ; '.join(reasons)})
    return issues

REVIEW_HEADERS=HEADERS+['Motif de vérification','Écriture FEC','Référence PNM source','Libellé FEC original','Candidats PNM']

def split_exports(rows):
    """Allocate unique piece IDs, then quarantine complete source entries."""
    import re
    from parametrage import weight_issues
    groups=defaultdict(list)
    for r in rows:groups[r['JournalCode'],r['EcritureNum']].append(r)
    bad_weights={x['Identifiant'] for x in weight_issues(rows)}
    ready=[];review=[]
    for index,((journal,entry),rs) in enumerate(groups.items(),1):
        unique={r['IdentifiantLigneSource']:r for r in rs}
        refs=sorted({r['NumeroPieceComptablePNM'] for r in rs if r['NumeroPieceComptablePNM']})
        base=refs[0] if len(refs)==1 else 'SAISIE'
        # Globally unique ordinal prevents collisions even after journal remapping.
        ref=f'{journal}-{base}-{index:06d}'
        title=next((r['EcritureLib'] for r in rs if r['EcritureLib'].strip()),entry)
        reasons=[]
        if len({r['EcritureDate'] for r in rs})!=1:reasons.append('Dates différentes dans la pièce source')
        balance=sum((amount(r['Debit'])-amount(r['Credit']) for r in unique.values()),Decimal(0))
        if balance:reasons.append(f'Pièce déséquilibrée : {balance:.2f}')
        if any(r['StatutRapprochement'].startswith('À RAPPROCHER') for r in rs):reasons.append('Rapprochement PNM ambigu')
        if len(refs)>1:reasons.append('Plusieurs références PNM dans la pièce FEC')
        if any(r['IdentifiantLigneSource'] in bad_weights for r in rs):reasons.append('Poids analytique invalide')
        if not re.fullmatch('[A-Za-z]{1,5}',journal):reasons.append('Code journal à paramétrer (1 à 5 lettres)')
        for r in unique.values():
            acc=r['CompteNum']
            if not (acc.isdigit() or (acc.startswith(('401','411','410','421','455','467')) and re.fullmatch('[A-Za-z0-9]+',acc))):
                reasons.append('Numéro de compte incompatible');break
        for r in rs:
            out=dict(zip(HEADERS,[r['EcritureDate'],journal,r['CompteNum'],r['CompteLib'],r['PieceRef'],'','',title,ref,r['Debit'],r['Credit'],r['FamilleAnalytique'],r['CategorieAnalytique'],r['IdentifiantLigneSource'],r.get('EcritureLet',''),r['PoidsAnalytique']]))
            if reasons:
                out.update({'Motif de vérification':' ; '.join(reasons),'Écriture FEC':entry,'Référence PNM source':r['NumeroPieceComptablePNM'],'Libellé FEC original':r['EcritureLib'],'Candidats PNM':r.get('CandidatsPNM','')})
                review.append(out)
            else:ready.append(out)
    assert not validate_template(ready), 'Contrôle interne de pièces échoué'
    assert len(ready)+len(review)==len(rows)
    assert not ({r['Identifiant de ligne'] for r in ready}&{r['Identifiant de ligne'] for r in review})
    return ready,review
