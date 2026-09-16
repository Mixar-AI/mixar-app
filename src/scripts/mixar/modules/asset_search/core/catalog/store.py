# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Local, transactional asset inventory. Absolute locations never leave this store."""

import json
import re
import sqlite3
import uuid
from pathlib import Path


class Catalog:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS libraries (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, root TEXT UNIQUE NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'new',
                message TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY, library_id TEXT NOT NULL, file TEXT NOT NULL,
                kind TEXT NOT NULL, name TEXT NOT NULL, revision TEXT NOT NULL,
                metadata TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS asset_library ON assets(library_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS asset_fts USING fts5(
                id UNINDEXED, name, tags, description, tokenize='porter unicode61');
        ''')

    def source_id(self):
        existing = self.db.execute("SELECT value FROM settings WHERE key='source_id'").fetchone()
        if existing:
            return existing[0]
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('source_id',?)", (str(uuid.uuid4()),))
        return self.db.execute("SELECT value FROM settings WHERE key='source_id'").fetchone()[0]

    def close(self):
        self.db.close()

    def configure(self, libraries):
        """Disable removed preferences; an offline library is still configured."""
        desired = {str(Path(item['root']).expanduser().resolve()): item['name'] for item in libraries}
        current = {row['root']: row['name'] for row in self.db.execute(
            'SELECT root,name FROM libraries WHERE enabled=1')}
        if desired == current:
            return self.libraries(private=True)
        # Read-only status/search polling must not contend with the scanner's
        # snapshot transaction. Write only when GUI preferences actually change.
        with self.db:
            self.db.execute('UPDATE libraries SET enabled=0')
            for root, name in desired.items():
                self.db.execute('''INSERT INTO libraries(id,name,root) VALUES(?,?,?)
                    ON CONFLICT(root) DO UPDATE SET name=excluded.name, enabled=1''',
                    (str(uuid.uuid4()), name, root))
        return self.libraries(private=True)

    def libraries(self, private=False):
        rows = self.db.execute('''SELECT l.*, count(a.id) asset_count FROM libraries l
            LEFT JOIN assets a ON a.library_id=l.id WHERE l.enabled=1 GROUP BY l.id
            ORDER BY l.name''').fetchall()
        return [{k: r[k] for k in r.keys() if private or k != 'root'} for r in rows]

    def records(self, library_id):
        return [dict(r) for r in self.db.execute(
            'SELECT * FROM assets WHERE library_id=?', (library_id,))]

    def status(self, library_id, status, message=''):
        with self.db:
            self.db.execute('UPDATE libraries SET status=?,message=? WHERE id=?',
                            (status, message, library_id))

    def replace(self, library_id, records):
        """Commit a COMPLETE library snapshot only. Failed scans never call this."""
        with self.db:
            self.db.execute('DELETE FROM asset_fts WHERE id IN '
                            '(SELECT id FROM assets WHERE library_id=?)', (library_id,))
            self.db.execute('DELETE FROM assets WHERE library_id=?', (library_id,))
            for item in records:
                aid = str(uuid.uuid5(uuid.UUID(library_id),
                                    json.dumps([item['file'], item['kind'], item['name']])))
                meta = item['metadata']
                if isinstance(meta, str):
                    meta = json.loads(meta)
                self.db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?)',
                    (aid, library_id, item['file'], item['kind'], item['name'],
                     item['revision'], json.dumps(meta)))
                self.db.execute('INSERT INTO asset_fts VALUES(?,?,?,?)',
                    (aid, item['name'], ' '.join(meta.get('tags', [])),
                     meta.get('description', ''),))
            self.db.execute("UPDATE libraries SET status='ready',message='' WHERE id=?",
                            (library_id,))

    def resolve(self, asset_id, revision=None):
        row = self.db.execute('''SELECT a.*,l.name library,l.root,l.status FROM assets a
            JOIN libraries l ON l.id=a.library_id WHERE a.id=? AND l.enabled=1''',
            (asset_id,)).fetchone()
        if row is None:
            raise ValueError('Asset is no longer in a configured library; search again')
        item = dict(row)
        if revision and item['revision'] != revision:
            raise ValueError('Asset changed since search; refresh the result before placing it')
        path = (Path(item['root']) / item['file']).resolve()
        if not path.is_relative_to(Path(item['root'])) or not path.is_file():
            raise ValueError('Asset library is offline or the asset was removed')
        item['path'] = str(path)
        return item

    @staticmethod
    def public(row):
        meta = json.loads(row['metadata'])
        return {'asset_id': row['id'], 'revision': row['revision'],
                'name': row['name'], 'library_id': row['library_id'],
                'library': row['library'], 'blend_file': row['file'],
                'kind': row['kind'], 'type': meta.get('type') or ('Collection' if row['kind'] == 'COLLECTION' else 'MESH'),
                'tags': meta.get('tags', []), 'description': meta.get('description', ''),
                'available': row['status'] == 'ready', 'scatterable': meta.get('scatterable', False)}

    def search(self, query='', libraries=None, limit=20, scatterable=False):
        limit = max(1, min(int(limit), 100))
        params, where = [], ['l.enabled=1']
        if libraries:
            marks = ','.join('?' for _ in libraries)
            where.append(f'(l.id IN ({marks}) OR l.name IN ({marks}))')
            params.extend(libraries); params.extend(libraries)
        tokens = re.findall(r'[^\W_]+', str(query), flags=re.UNICODE)[:32]
        join, order = '', 'a.name,a.id'
        if tokens:
            join = 'JOIN asset_fts ON asset_fts.id=a.id'
            where.append('asset_fts MATCH ?')
            params.append(' OR '.join('"' + t + '"' for t in tokens))
            order = 'bm25(asset_fts,0,6,4,1),a.id'
        if scatterable:
            where.append("json_extract(a.metadata,'$.scatterable')=1")
        rows = self.db.execute(f'''SELECT a.*,l.name library,l.status FROM assets a
            JOIN libraries l ON l.id=a.library_id {join}
            WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?''',
            (*params, limit)).fetchall()
        return [self.public(row) for row in rows]

    def match(self, candidates, libraries=None):
        """Resolve semantic hits against configured local inventory; no phantom files."""
        hits = []
        for candidate in candidates[:100]:
            meta = candidate.get('metadata') or candidate
            rows = self.db.execute('''SELECT a.*,l.name library,l.status FROM assets a
                JOIN libraries l ON l.id=a.library_id WHERE l.enabled=1 AND
                l.name=? AND a.file=? AND a.name=? ORDER BY a.id''',
                (meta.get('library', ''), str(meta.get('blend_file', '')).replace('\\', '/'),
                 meta.get('name') or candidate.get('asset_name', ''))).fetchall()
            for row in rows:
                if libraries and row['library'] not in libraries and row['library_id'] not in libraries:
                    continue
                kind = str(meta.get('type') or candidate.get('asset_type') or '').lower()
                if kind and (kind.startswith('collection')) != (row['kind'] == 'COLLECTION'):
                    continue
                if meta.get('revision') and meta['revision'] != row['revision']:
                    continue
                if meta.get('source_id') and meta['source_id'] != self.source_id():
                    continue
                hit = self.public(row)
                hit['semantic_score'] = candidate.get('similarity_score', candidate.get('score', 0))
                hits.append(hit)
        return hits


def fuse(lexical, semantic, limit=20):
    """Reciprocal rank fusion; cosine similarities are not probabilities."""
    scores, hits = {}, {}
    for result_set in (lexical, semantic):
        seen = set()
        for rank, hit in enumerate(result_set):
            aid = hit['asset_id']
            if aid in seen:
                continue
            seen.add(aid)
            scores[aid] = scores.get(aid, 0) + 1 / (60 + rank + 1)
            hits[aid] = {**hits.get(aid, {}), **hit}
    return [hits[k] for k in sorted(scores, key=lambda k: (-scores[k], k))[:limit]]
