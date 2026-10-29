import csv,io,json,hashlib,unicodedata
from collections import defaultdict,Counter
from decimal import Decimal as D
from datetime import datetime
from zipfile import ZipFile,ZIP_DEFLATED
from pnm import parse_pnm,amount,money,csv_bytes,ConversionError

def label(s):
    s=unicodedata.normalize('NFKD',s.replace('€','_')).upper()
    return ''.join(c for c in s if c.isalnum())[:20]

def read_fec(raw,encoding='auto'):
    encs=['utf-8-sig','cp1252'] if encoding=='auto' else [encoding]
    for enc in encs:
        try:txt=raw.decode(enc);break
        except UnicodeDecodeError:continue
    else:raise ConversionError('Encodage FEC non reconnu.')
    sep='\t' if '\t' in txt.splitlines()[0] else ';'
    reader=csv.DictReader(io.StringIO(txt),delimiter=sep)
    needed=['JournalCode','EcritureNum','EcritureDate','CompteNum','CompAuxNum','PieceRef','PieceDate','EcritureLib','Debit','Credit']
    if not set(needed)<=set(reader.fieldnames or []):raise ConversionError('Colonnes FEC obligatoires manquantes.')
    rows=[]
    for i,row in enumerate(reader,2):
        r={k:(v or '').strip() for k,v in row.items() if k}
        try:
            r['_date']=datetime.strptime(r['EcritureDate'],'%Y%m%d').date()
            r['_signed']=amount(r['Debit'])-amount(r['Credit'])
            if amount(r['Debit'])<0 or amount(r['Credit'])<0 or (amount(r['Debit']) and amount(r['Credit'])):raise ConversionError('Débit/crédit inhabituels.')
        except (ValueError,ConversionError) as e:raise ConversionError(f'FEC ligne {i} : {e}')
        r['_line']=i;rows.append(r)
    if not rows:raise ConversionError('FEC vide.')
    return rows

def coref(r):return(r['JournalCode'][:3],r['_date'],r['CompteNum'],r['CompAuxNum'],r['_signed'])
def corep(r):return(r.journal,r.date,r.account,r.sub if r.kind=='X' else '',r.signed)
def afingerprint(r):return tuple(sorted((a.plan,a.sub,a.signed) for a in r.allocations))

def reconcile(fraw,praw,pencoding='cp850',manual=None):
    f=read_fec(fraw);p=parse_pnm(praw,encoding=pencoding);manual=manual or {}
    if Counter(coref(r) for r in f)!=Counter(corep(r) for r in p.records):
        raise ConversionError('FEC et PNM ne contiennent pas les mêmes lignes comptables (dates, journaux, comptes, auxiliaires ou montants). Vérifiez la période et les simulations.')
    # Never infer a link from row order or from an amount alone.
    fmap={r['_line']:r for r in f};pmap={r.line:r for r in p.records};links={};used=set();methods={}
    def attach(fi,pi,method):links[fi]=pi;used.add(pi);methods[fi]=method
    for fi,pi in manual.items():
        fi=int(fi);pi=int(pi)
        if fi not in fmap or pi not in pmap or coref(fmap[fi])!=corep(pmap[pi]) or pi in used:raise ConversionError('Rapprochement manuel incompatible ou réutilisé.')
        attach(fi,pi,'Manuel')
    def buckets(extra=False):
        fb=defaultdict(list);pb=defaultdict(list)
        for r in f:
            if r['_line'] not in links:fb[coref(r)+(label(r['EcritureLib']),) if extra else coref(r)].append(r['_line'])
        for r in p.records:
            if r.line not in used:pb[corep(r)+(label(r.label),) if extra else corep(r)].append(r.line)
        return fb,pb
    for extra in [True,False]:
        fb,pb=buckets(extra)
        for k,ii in fb.items():
            jj=pb.get(k,[])
            if len(ii)==len(jj)==1:attach(ii[0],jj[0],'Clé complète + libellé' if extra else 'Clé comptable unique')
    # Match whole balanced/document groups by their complete multiset, not sequence.
    fg=defaultdict(list);pg=defaultdict(list)
    for r in f:fg[r['JournalCode'],r['EcritureNum']].append(r)
    for r in p.records:pg[r.piece].append(r)
    fs=defaultdict(list);ps=defaultdict(list)
    for k,rs in fg.items():fs[tuple(sorted(coref(r) for r in rs))].append(k)
    for k,rs in pg.items():ps[tuple(sorted(corep(r) for r in rs))].append(k)
    for sig,keys in fs.items():
        pkeys=ps.get(sig,[])
        if len(keys)!=1 or len(pkeys)!=1:continue
        fr=fg[keys[0]];pr=pg[pkeys[0]]
        # Reject a whole-piece inference conflicting with a proven individual match.
        ids={r.line for r in pr}
        if any(r['_line'] in links and links[r['_line']] not in ids for r in fr):continue
        for r in fr:
            fi=r['_line']
            if fi in links:continue
            cand=[x for x in pr if x.line not in used and corep(x)==coref(r)]
            tight=[x for x in cand if label(x.label)==label(r['EcritureLib'])]
            if tight:cand=tight
            if len(cand)==1 or (cand and len({afingerprint(x) for x in cand})==1):
                attach(fi,cand[0].line,'Signature complète de pièce unique')
    # A unique sibling-vote links a source piece to its FEC entry, only when reciprocal.
    for _ in range(3):
        votes=defaultdict(set);reverse=defaultdict(set)
        for fi,pi in links.items():
            fg=(fmap[fi]['JournalCode'],fmap[fi]['EcritureNum']);pg=pmap[pi].piece
            votes[fg].add(pg);reverse[pg].add(fg)
        changed=False;fb,pb=buckets()
        for k,ii in fb.items():
            for fi in ii:
                fg=(fmap[fi]['JournalCode'],fmap[fi]['EcritureNum'])
                if len(votes.get(fg,set()))!=1:continue
                pg=next(iter(votes[fg]))
                if len(reverse[pg])!=1:continue
                candidates=[pi for pi in pb.get(k,[]) if pi not in used and pmap[pi].piece==pg]
                if len(candidates)==1:attach(fi,candidates[0],'Pièce rapprochée par ses autres lignes');changed=True
        if not changed:break
    # Interchangeable duplicate rows are safe only if piece, label and analytic amounts agree.
    fb,pb=buckets()
    for k,ii in fb.items():
        jj=[pi for pi in pb.get(k,[]) if pi not in used]
        if len(ii)==len(jj) and jj and len({(pmap[pi].ref,label(pmap[pi].label),afingerprint(pmap[pi])) for pi in jj})==1:
            for fi,pi in zip(sorted(ii),sorted(jj)):attach(fi,pi,'Lignes équivalentes (même référence et analytique)')
    # The FEC suffix is the accounting piece number (confirmed by the user).
    # Use it only for unresolved whole pieces with identical accounting signatures.
    # Existing proven links must agree, and competing FEC pieces cannot claim it.
    fec_groups=defaultdict(list);pnm_groups=defaultdict(list)
    for r in f:fec_groups[r['JournalCode'],r['EcritureNum']].append(r)
    for r in p.records:pnm_groups[r.piece].append(r)
    indexed=defaultdict(list)
    for pk,pr in pnm_groups.items():
        indexed[pr[0].ref,tuple(sorted(corep(x) for x in pr))].append(pk)
    proposals={};claims=defaultdict(list)
    for fk,fr in fec_groups.items():
        if all(x['_line'] in links for x in fr):continue
        number=fk[1].rsplit('_',1)
        if len(number)!=2 or not number[1]:continue
        choices=indexed.get((number[1],tuple(sorted(coref(x) for x in fr))),[])
        if len(choices)!=1:continue
        pk=choices[0];pr=pnm_groups[pk];pids={x.line for x in pr}
        own={links[x['_line']] for x in fr if x['_line'] in links}
        if not own<=pids or (pids & used)-own:continue
        proposals[fk]=pk;claims[pk].append(fk)
    for fk,pk in proposals.items():
        if len(claims[pk])!=1:continue
        fb=defaultdict(list);pb=defaultdict(list)
        for r in fec_groups[fk]:
            if r['_line'] not in links:fb[coref(r)].append(r)
        for r in pnm_groups[pk]:
            if r.line not in used:pb[corep(r)].append(r)
        for k,fr in fb.items():
            pr=pb[k]
            if len(fr)!=len(pr):continue
            if len(fr)==1 or len({afingerprint(x) for x in pr})==1:
                for a,b in zip(fr,pr):attach(a['_line'],b.line,'Numéro de pièce suffixe + signature complète')
    unresolved=[]
    fb,pb=buckets()
    for k,ii in fb.items():
        for fi in ii:unresolved.append({'Ligne FEC':fi,'Date':fmap[fi]['_date'].strftime('%d/%m/%Y'),'Écriture FEC':fmap[fi]['EcritureNum'],
            'Facture':fmap[fi]['PieceRef'],'Compte':fmap[fi]['CompteNum'],'Libellé':fmap[fi]['EcritureLib'],
            'Candidats PNM':', '.join(str(pi) for pi in pb.get(k,[]) if pi not in used)})
    return f,p,links,methods,unresolved

def original_fec(raw):
    for enc in ['utf-8-sig','cp1252']:
        try:text=raw.decode(enc);break
        except UnicodeDecodeError:continue
    else:raise ConversionError('Encodage FEC non reconnu.')
    first=text.splitlines()[0] if text.splitlines() else ''
    sep='\t' if '\t' in first else ';'
    reader=csv.reader(io.StringIO(text),delimiter=sep)
    headers=next(reader,[])
    if not headers or len(headers)!=len(set(headers)):raise ConversionError('En-têtes FEC vides ou dupliqués.')
    rows=[]
    for i,values in enumerate(reader,2):
        if not values:continue
        if len(values)!=len(headers):raise ConversionError(f'Ligne FEC {i} : nombre de colonnes incorrect.')
        rows.append(dict(zip(headers,values)))
    return headers,rows

EXTRA=['NumeroPieceComptablePNM','FamilleAnalytique','CategorieAnalytique','PoidsAnalytique',
       'MontantAnalytiquePNM','IdentifiantLigneSource','StatutRapprochement','DetailAnalytiquePNM','CandidatsPNM']

def collapse_accounts(rows,headers):
    """One account/label pair; auxiliary takes precedence, without changing its code."""
    fields=[k for k in headers if k not in ('CompAuxNum','CompAuxLib')]
    if 'CompteLib' not in fields:fields.insert(fields.index('CompteNum')+1,'CompteLib')
    for row in rows:
        auxiliary=row.get('CompAuxNum','')
        if auxiliary.strip():
            row['CompteNum']=auxiliary
            if row.get('CompAuxLib','').strip():row['CompteLib']=row['CompAuxLib']
        row.setdefault('CompteLib','')
        row.pop('CompAuxNum',None);row.pop('CompAuxLib',None)
    return fields

def enrich(raw,result,family='Plan 1',mode='original'):
    """Preserve every original FEC cell. Never repair amounts, dates or lettering."""
    headers,original=original_fec(raw)
    if set(headers)&set(EXTRA):raise ConversionError('Le FEC contient déjà une colonne d’enrichissement. Utilisez le FEC initial.')
    f,p,links,methods,unresolved=result
    if len(original)!=len(f):raise ConversionError('Nombre de lignes FEC incohérent.')
    pm={r.line:r for r in p.records};issues={r['Ligne FEC']:r for r in unresolved}
    out=[];multi=0;inconsistent=0
    for source,parsed in zip(original,f):
        fi=parsed['_line'];r=pm.get(links.get(fi));entries=[]
        if r:
            for a in r.allocations:
                entries.append({'ligne_pnm':a.line,'plan':a.plan,'section':a.sub,'montant_signe':str(a.signed)})
        cats=defaultdict(D)
        for a in entries:cats[a['plan'],a['section']]+=D(a['montant_signe'])
        parts=[];totals=defaultdict(D)
        for (plan,cat),n in cats.items():
            totals[plan]+=n
            weight=n/parsed['_signed'] if parsed['_signed'] else None
            parts.append({'family':family if plan=='1' else f'Plan {plan}','category':cat,'amount':money(n),
                          'weight':format(weight.quantize(D('.000000000001')),'f').replace('.',',') if weight is not None else ''})
        bad=bool(parts) and (any(n!=parsed['_signed'] for n in totals.values()) or any(D(x['weight'].replace(',','.'))<=0 for x in parts if x['weight']))
        if bad:inconsistent+=1
        if len(parts)>1:multi+=1
        candidates=[]
        if not r:
            for pi in issues.get(fi,{}).get('Candidats PNM','').split(', '):
                if not pi:continue
                c=pm[int(pi)]
                candidates.append({'ligne_pnm':c.line,'piece_comptable':c.ref,'libelle':c.label,
                  'analytique':[{'plan':a.plan,'section':a.sub,'montant_signe':str(a.signed)} for a in c.allocations]})
        additions={'NumeroPieceComptablePNM':r.ref if r else '',
            'FamilleAnalytique':' | '.join(x['family'] for x in parts),
            'CategorieAnalytique':' | '.join(x['category'] for x in parts),
            'PoidsAnalytique':' | '.join(x['weight'] for x in parts),
            'MontantAnalytiquePNM':' | '.join(x['amount'] for x in parts),
            'IdentifiantLigneSource':f'FEC-{fi:07d}',
            'StatutRapprochement':('RAPPROCHÉ — ÉCART ANALYTIQUE SOURCE' if bad else 'RAPPROCHÉ') if r else 'À RAPPROCHER',
            'DetailAnalytiquePNM':json.dumps(entries,ensure_ascii=False) if entries else '',
            'CandidatsPNM':json.dumps(candidates,ensure_ascii=False) if candidates else ''}
        if mode=='categories' and parts:
            for x in parts:out.append(dict(source,**dict(additions,FamilleAnalytique=x['family'],CategorieAnalytique=x['category'],PoidsAnalytique=x['weight'],MontantAnalytiquePNM=x['amount'])))
        else:out.append(dict(source,**additions))
    unique={r['IdentifiantLigneSource']:r for r in out}
    for parsed,source in zip(f,original):
        exported=unique[f'FEC-{parsed["_line"]:07d}']
        if any(exported[k]!=source[k] for k in headers):raise ConversionError('Une cellule du FEC a été modifiée : export refusé.')
    report={'source_rows':len(original),'output_rows':len(out),'original_columns':len(headers),'modified_cells':0,
        'matched':len(links),'unresolved':len(unresolved),'multi_categories':multi,'analytic_discrepancies':inconsistent,
        'lettered_rows':sum(bool(r.get('EcritureLet','').strip()) for r in original)}
    output_headers=collapse_accounts(out,headers)
    report['output_base_columns']=len(output_headers)
    report['accounts_promoted']=sum(bool(r.get('CompAuxNum','').strip()) for r in original)
    report['aux_labels_missing']=sum(bool(r.get('CompAuxNum','').strip()) and not r.get('CompAuxLib','').strip() for r in original)
    return out,output_headers+EXTRA,report
