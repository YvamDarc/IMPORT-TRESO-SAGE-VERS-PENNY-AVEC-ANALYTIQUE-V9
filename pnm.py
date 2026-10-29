"""Conversion PNM Sage → import Écritures Pennylane. Aucun appel réseau."""
from __future__ import annotations
import csv, io, re, json, hashlib, calendar
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from zipfile import ZipFile, ZIP_DEFLATED

D = Decimal
class ConversionError(ValueError): pass

def amount(value):
    try:
        n = D(str(value).strip().replace(' ', '').replace(',', '.'))
        if not n.is_finite() or n != n.quantize(D('.01')): raise ValueError()
        return n
    except (InvalidOperation, ValueError): raise ConversionError(f'Montant invalide : {value!r}')

def money(n): return format(n, '.2f').replace('.', ',')
def parse_date(s):
    try: return datetime.strptime(s, '%d%m%y').date()
    except ValueError: raise ConversionError(f'Date Sage invalide : {s!r}')

@dataclass
class Record:
    line: int
    journal: str
    date: date
    account: str
    kind: str
    sub: str
    ref: str
    label: str
    due: str
    signed: Decimal
    source_id: str
    plan: str
    status: str = 'N'
    allocations: list = field(default_factory=list)
    @property
    def uid(self): return f'L{self.line:07d}'
    @property
    def piece(self): return f'{self.journal}-{self.date:%Y%m%d}-{self.ref or "SANSREF"}'

@dataclass
class Dataset:
    company: str
    encoding: str
    digest: str
    records: list
    analytic_count: int
    headers: int
    excluded_simulations: int = 0

def parse_pnm(raw: bytes, encoding='auto', headers=1, include_simulations=False):
    if encoding == 'auto':
        try: text = raw.decode('utf-8-sig'); encoding = 'utf-8-sig'
        except UnicodeDecodeError:
            encoding = 'cp1252'
            try: text = raw.decode(encoding)
            except UnicodeDecodeError: raise ConversionError('Encodage non reconnu : choisissez CP850 ou ISO-8859-1.')
    else:
        try: text = raw.decode(encoding)
        except UnicodeDecodeError as e: raise ConversionError(str(e))
    lines = text.splitlines()
    if not 0 <= headers < len(lines): raise ConversionError('Nombre de lignes d’en-tête incorrect.')
    records = []; parent = None; analytic_count = 0
    for no, line in enumerate(lines[headers:], headers + 1):
        if not line.strip(): continue
        try:
            if len(line) not in (105,112,138,141,164,199):
                raise ConversionError(f'Longueur {len(line)} non prise en charge ; fichier à largeur fixe requis.')
            s = line.ljust(199)
            kind = s[24]
            if kind not in (' ', 'G', 'X', 'A'): raise ConversionError(f'Type {kind!r} non pris en charge (les échéances E doivent être traitées séparément).')
            if s[83] not in 'DC': raise ConversionError('Sens autre que D/C.')
            n = amount(s[84:104])
            if s[104] not in ('N','A','S',' '): raise ConversionError('Type d’écriture inconnu.')
            if s[138:141].strip() not in ('', 'EUR') or s[141:164].strip():
                raise ConversionError('Devises étrangères non prises en charge ; conversion EUR requise.')
            if s[174:].strip(): raise ConversionError('Extension de section analytique non prise en charge.')
            r = Record(no,s[:3].strip(),parse_date(s[3:9]),s[11:24].strip(),kind,
                       s[25:38].strip(),s[38:51].strip(),s[51:76].strip(),
                       parse_date(s[77:83]).strftime('%d/%m/%Y') if s[77:83].strip() else '',
                       n if s[83]=='D' else -n,s[105:112].strip(),s[164:174].strip() or '1')
            r.status=s[104]
            if not r.journal or not re.fullmatch(r'\d+',r.account): raise ConversionError('Journal absent ou compte général non numérique.')
            if kind == 'A':
                if parent is None: raise ConversionError('Ventilation orpheline.')
                if (r.journal,r.date,r.account,r.ref,r.source_id) != (parent.journal,parent.date,parent.account,parent.ref,parent.source_id):
                    raise ConversionError('La ventilation ne correspond pas à la ligne comptable précédente.')
                if not r.sub: raise ConversionError('Section analytique vide.')
                parent.allocations.append(r); analytic_count += 1
            else:
                if kind == 'X' and not r.sub: raise ConversionError('Auxiliaire vide.')
                records.append(r); parent = r
        except ConversionError as e: raise ConversionError(f'Ligne {no} : {e}')
    excluded=sum(r.status=='S' for r in records) if not include_simulations else 0
    if not include_simulations: records=[r for r in records if r.status!='S']
    analytic_count=sum(len(r.allocations) for r in records)
    if not records: raise ConversionError('Aucune ligne comptable hors exclusions.')
    return Dataset(lines[0].strip() if headers else '',encoding,hashlib.sha256(raw).hexdigest(),records,analytic_count,headers,excluded)

def csv_bytes(rows, fields=None):
    rows=list(rows);out=io.StringIO(newline='')
    fields=fields or (list(rows[0]) if rows else ['Information'])
    writer=csv.DictWriter(out,fieldnames=fields,delimiter=';',lineterminator='\r\n')
    writer.writeheader();writer.writerows(rows)
    return out.getvalue().encode('utf-8-sig')
