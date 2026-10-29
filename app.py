import hashlib,json,csv,io
from pathlib import Path
import streamlit as st
import pandas as pd
from fusion import reconcile,enrich,csv_bytes,ConversionError
from trame import HEADERS,REVIEW_HEADERS,split_exports
from parametrage import mapping_tables,apply_mappings,weight_issues,normalize_invalid_weights,ambiguity_review,remap_reserved_clients
# Versioned session data: old export tuples must never survive a schema change.
CACHE_SCHEMA = 'fec-enrichi-pennylane-v9'
REQUIRED_REPORT = {'source_rows','output_rows','accounts_promoted','lettered_rows',
                   'unresolved','aux_labels_missing','analytic_discrepancies','output_base_columns'}

def normalize_export(raw,result,rows,fields,report):
    # Compatible with the previous fusion.py: derive account data from the source,
    # not missing report keys and not a potentially stale already-collapsed export.
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:text=raw.decode('cp1252')
    sep='\t' if '\t' in text.splitlines()[0] else ';'
    source=list(csv.DictReader(io.StringIO(text),delimiter=sep))
    if len(source)!=len(result[0]):raise ConversionError('Nombre de lignes source incohérent.')
    by_id={f'FEC-{parsed["_line"]:07d}':original for parsed,original in zip(result[0],source)}
    headers=list(source[0])
    for row in rows:
        original=by_id.get(row.get('IdentifiantLigneSource'))
        if original is None:raise ConversionError('Version du moteur incompatible : mettez à jour fusion.py.')
        aux=original.get('CompAuxNum','') or ''
        row['CompteNum']=aux if aux.strip() else original['CompteNum']
        aux_label=original.get('CompAuxLib','') or ''
        row['CompteLib']=aux_label if aux.strip() and aux_label.strip() else (original.get('CompteLib','') or '')
        row.pop('CompAuxNum',None);row.pop('CompAuxLib',None)
        for name in headers:
            if name not in ('CompteNum','CompteLib','CompAuxNum','CompAuxLib') and row.get(name)!=original[name]:
                raise ConversionError('Une colonne FEC a changé : régénérez avec les fichiers source.')
    fields=[k for k in fields if k not in ('CompAuxNum','CompAuxLib')]
    if 'CompteLib' not in fields:fields.insert(fields.index('CompteNum')+1,'CompteLib')
    base=[k for k in headers if k not in ('CompAuxNum','CompAuxLib')]
    if 'CompteLib' not in base:base.append('CompteLib')
    report=dict(report)
    report.update(source_rows=len(source),output_rows=len(rows),
        accounts_promoted=sum(bool((r.get('CompAuxNum') or '').strip()) for r in source),
        aux_labels_missing=sum(bool((r.get('CompAuxNum') or '').strip()) and not (r.get('CompAuxLib') or '').strip() for r in source),
        lettered_rows=sum(bool((r.get('EcritureLet') or '').strip()) for r in source),
        unresolved=len(result[4]),output_base_columns=len(base))
    if 'analytic_discrepancies' not in report:
        report['analytic_discrepancies']=len({r['IdentifiantLigneSource'] for r in rows if 'ÉCART ANALYTIQUE' in r.get('StatutRapprochement','')})
    return rows,fields,report,csv_bytes(rows,fields)

def valid_export(value):
    return (isinstance(value,(tuple,list)) and len(value)==4
            and isinstance(value[2],dict) and REQUIRED_REPORT <= value[2].keys()
            and 'CompAuxNum' not in value[1] and 'CompAuxLib' not in value[1])

st.set_page_config(page_title='FEC enrichi avec analytique',page_icon='📑',layout='wide')
st.title('Ton FEC complet + l’analytique')
st.caption('Version 9 · comptes numériques · comptes clients réservés corrigés · deux fichiers · trame Pennylane · contrôle des ambiguïtés · pièces comptables · analytique par ligne · journaux et banques paramétrables')
st.write('Un seul compte et son libellé : l’auxiliaire est prioritaire sur le collectif. Dates, lettrage, références et montants sont conservés ; l’analytique est ajoutée. Les journaux et comptes bancaires changent uniquement selon ton paramétrage.')
with st.sidebar:
    ff=st.file_uploader('FEC initial',type=['txt','csv','fec'])
    pp=st.file_uploader('PNM avec analytique',type=['pnm','txt'])
    enc=st.selectbox('Encodage PNM',['cp850','cp1252','utf-8-sig'])
    family=st.text_input('Nom de la famille analytique','Plan 1')
    mode='Une ligne par catégorie analytique'
    st.caption('Export Pennylane : une catégorie par ligne, identifiant commun et poids.')
    st.caption('1 ligne d’en-tête dans chaque fichier. Aucun envoi à Pennylane.')
if not ff or not pp:st.stop()
raw=ff.getvalue();pnm=pp.getvalue()
engine_path=Path(__file__).with_name('fusion.py')
engine_hash=hashlib.sha256(engine_path.read_bytes()).hexdigest() if engine_path.exists() else 'embedded'
schema_key=(CACHE_SCHEMA,engine_hash)
if st.session_state.get('_cache_schema')!=schema_key:
    for stale in ('source_key','result','export_key','export'):
        st.session_state.pop(stale,None)
    st.session_state['_cache_schema']=schema_key
key=hashlib.sha256(raw+pnm+enc.encode()).hexdigest()
try:
    if st.session_state.get('source_key')!=key or 'result' not in st.session_state:
        with st.spinner('Rapprochement des deux fichiers…'):
            result=reconcile(raw,pnm,enc)
        st.session_state['result']=result;st.session_state['source_key']=key
    result=st.session_state['result']
    ek=(schema_key,key,family,mode)
    if st.session_state.get('export_key')!=ek or not valid_export(st.session_state.get('export')):
        rows,fields,report=enrich(raw,result,family,'original' if mode.startswith('Une ligne par ligne') else 'categories')
        st.session_state['export']=normalize_export(raw,result,rows,fields,report);st.session_state['export_key']=ek
    rows,fields,report,content=st.session_state['export']
except (ConversionError,ValueError) as e:st.error(str(e));st.stop()
a,b,c,d=st.columns(4)
a.metric('Lignes du FEC',report['source_rows']);b.metric('Comptes auxiliaires repris',report['accounts_promoted']);c.metric('Lignes avec lettrage conservé',report['lettered_rows']);d.metric('À rapprocher',report['unresolved'])
st.success('CompteNum et CompteLib sont les seules colonnes de compte et de libellé de compte. CompAuxNum et CompAuxLib ont été fusionnées puis supprimées de l’export.')
if report['aux_labels_missing']:st.caption(f"{report['aux_labels_missing']} auxiliaires n’ont pas de libellé : le libellé du compte général est conservé en remplacement.")
if report['unresolved']:st.warning(f"{report['unresolved']} correspondances sont ambiguës. Les ajouts concernés restent vides ; les candidats et leur analytique sont consultables ci-dessous. Aucun choix au hasard.")
if report['analytic_discrepancies']:st.caption(f"{report['analytic_discrepancies']} écarts analytiques source sont signalés. Les montants source restent inchangés ; toute correction des poids est explicite.")
st.info('À mapper impérativement dans Pennylane : Identifiant de ligne ; Poids de la catégorie ; Catégorie ; Famille de catégories (colonnes de la trame). Les répétitions partagent le même identifiant : leurs débits/crédits ne doivent pas être additionnés.')
with st.expander('Renommer les journaux et les comptes bancaires',expanded=True):
    journal_defaults,bank_defaults=mapping_tables(rows)
    suggested={'10':'OD','50':'BNP','51':'CMB','60':'HA','70':'VT'}
    for item in journal_defaults:
        if item['Journal source'] in suggested:item['Code cible']=suggested[item['Journal source']]
    st.caption('Modifie les codes et libellés cibles. Les codes numériques connus sont proposés automatiquement : 10→OD, 50→BNP, 51→CMB, 60→HA, 70→VT. Les noms des journaux restent conservés. Tu peux modifier ces correspondances.')
    journals=st.data_editor(pd.DataFrame(journal_defaults),disabled=['Journal source'],hide_index=True,key='journals_'+key).to_dict('records')
    st.caption('Chaque remplacement de compte 512 s’applique à toutes ses occurrences, y compris les à-nouveaux et les OD. Les comptes fournisseurs/clients restent inchangés.')
    banks=st.data_editor(pd.DataFrame(bank_defaults),disabled=['Compte source','Journaux source'],hide_index=True,key='banks_'+key).to_dict('records') if bank_defaults else []
try:rows=apply_mappings(rows,journals,banks)
except ConversionError as e:st.error(str(e));st.stop()
with st.expander('Comptes clients réservés par Pennylane',expanded=True):
    st.caption('Les comptes commençant par 41106 ou 411900 sont convertis automatiquement en 4111… (exemple : 4110652 → 41110652) sur toutes leurs lignes, dans les deux fichiers. Aucun compte distinct n’est fusionné.')
    extra_clients=st.text_input('Autres comptes clients signalés comme standards par Pennylane (séparés par virgules)',key='reserved_extra_'+key)
    extras=[x.strip() for x in extra_clients.replace(';',',').split(',') if x.strip()]
    rows,client_mapping=remap_reserved_clients(rows,extras)
    if client_mapping:st.dataframe(pd.DataFrame(client_mapping),hide_index=True,width='stretch')
    else:st.caption('Aucun compte client réservé détecté dans ces sources.')
import re
invalid_journals=sorted({r['JournalCode'] for r in rows if not re.fullmatch(r'[A-Za-z]{1,5}',r['JournalCode'])})
if invalid_journals:st.warning('Codes journaux à adapter aux codes de ton dossier Pennylane : '+', '.join(invalid_journals)+'. Aucun remplacement automatique.')
issues=weight_issues(rows)
if issues and st.checkbox('Ramener explicitement à 100 % les répartitions invalides, au prorata de leurs poids positifs',value=False,key='normalize_'+key):
    rows=normalize_invalid_weights(rows)
    issues=weight_issues(rows)
    st.caption('Poids recalculés sur demande ; montants PNM d’origine conservés pour contrôle. Les montants analytiques importés seront proportionnels au montant comptable.')
if issues:
    st.warning(f"{len({r['Identifiant'] for r in issues})} lignes source ont des répartitions incompatibles avec les poids Pennylane. Corrige les poids ci-dessous (total 1 par ligne et famille). Les montants comptables ne sont pas modifiés.")
    corrected=st.data_editor(pd.DataFrame(issues),disabled=[k for k in issues[0] if k!='Poids'],hide_index=True,key='weights_'+key+'_'+family).to_dict('records')
    for item in corrected:rows[int(item['Ligne export'])]['PoidsAnalytique']=str(item['Poids'])
    remaining=weight_issues(rows)
    if remaining:st.warning('Des poids restent invalides : les pièces concernées seront placées dans le fichier à vérifier. Aucun montant ni poids n’est corrigé arbitrairement.')
if 'JournalLib' not in fields:
    fields=list(fields);fields.insert(fields.index('JournalCode')+1,'JournalLib')
content=csv_bytes(rows,fields)
st.subheader('Lignes problématiques — rapprochements à vérifier')
review,details=ambiguity_review(result)
if review:
    st.caption(f"{len(review)} lignes ambiguës ; {sum(r['Analytique possible']=='Oui' for r in review)} avec de l’analytique parmi les candidats. Les références ci-dessous sont celles des fichiers source, avant renommage des journaux et comptes.")
    only_analytic=st.checkbox('Afficher uniquement les lignes avec analytique possible',key='review_analytic')
    review_search=st.text_input('Filtrer les problèmes : facture, pièce, compte, libellé…',key='review_search')
    filtered=[r for r in review if (not only_analytic or r['Analytique possible']=='Oui') and (not review_search or review_search.casefold() in ' '.join(str(v) for v in r.values()).casefold())]
    st.dataframe(pd.DataFrame(filtered,columns=list(review[0])),hide_index=True,width='stretch')
    st.caption(f'{len(filtered)} lignes affichées. Cette liste contient tous les résultats du filtre, sans limite de 300 lignes.')
    if filtered:
        choices={r['Ligne FEC']:f"Ligne {r['Ligne FEC']} — {r['Date']} — {r['Libellé']} — pièce {r['Pièce FEC']}" for r in filtered}
        selected=st.selectbox('Examiner les candidats PNM d’une ligne',list(choices),format_func=lambda n:choices[n],key='review_line_'+key)
        st.dataframe(pd.DataFrame(details[selected]),hide_index=True,width='stretch')
        st.caption('Une ligne par ventilation analytique candidate. Aucun candidat n’est sélectionné automatiquement. Ces détails sont réservés au contrôle dans l’app.')
else:st.success('Aucune ligne ambiguë à vérifier.')
st.subheader('Télécharger les deux fichiers')
st.caption('Numéros de pièce uniques automatiques : journal + référence PNM + compteur. Libellé de ligne = PieceRef du FEC. Toute pièce problématique est écartée en entier du fichier d’import.')
ready,to_review=split_exports(rows)
x,y=st.columns(2)
x.metric('Lignes source prêtes',len({r['Identifiant de ligne'] for r in ready}))
y.metric('Lignes source à vérifier',len({r['Identifiant de ligne'] for r in to_review}))
x.download_button('1 — Télécharger les écritures à importer',csv_bytes(ready,HEADERS),'PENNYLANE_IMPORT.csv','text/csv',type='primary',disabled=not ready)
y.download_button('2 — Télécharger les écritures à vérifier',csv_bytes(to_review,REVIEW_HEADERS),'ECRITURES_A_VERIFIER.csv','text/csv')
st.caption('CSV UTF-8, point-virgule, 1 ligne d’en-tête. Les colonnes de la trame sont dans le même ordre ; Poids de la catégorie est ajouté pour les ventilations. Mapper Identifiant de ligne et Poids de la catégorie. Le deuxième fichier ne doit pas être importé avant correction.')
which=st.radio('Aperçu',['Écritures à importer','Écritures à vérifier'])
preview=ready if which=='Écritures à importer' else to_review
st.dataframe(pd.DataFrame(preview[:300],columns=HEADERS if which=='Écritures à importer' else REVIEW_HEADERS),hide_index=True,width='stretch')
st.caption('Toutes les lignes source sont réparties entre les deux fichiers, sans perte ni chevauchement. Dates, montants et lettrage sont conservés. Les pièces ambiguës restent en vérification.')
