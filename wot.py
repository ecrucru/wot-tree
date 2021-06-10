# Copyright (C) 2021 ecrucru
# https://github.com/ecrucru/wot-tree
# AGPL version 3

import sys
import os
import argparse
import sqlite3
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from time import sleep
import json


# Constants
APP_ID = ''                                         # Register at WarGaming with your phone to get an application ID
UNICODE_FONT = 'Segoe UI Symbol'                    # Pick according to your local computer
MAX_TIER = 10


# Useful functions
def _int(value):
    try:
        return int(value)
    except ValueError:
        return 0


def _bool(value):
    return 'X' if value in ['true', 'True', True] else ''


def _o2t(obj):
    result = ()
    for e in obj:
        result += (obj[e], )
    return result


def _field(data, path, default=''):
    if data in [None, '']:
        return ''
    keys = path.split('/')
    value = data
    for key in keys:
        if key.startswith('[') and key.endswith(']'):
            try:
                value = value[int(key[1:-1])]
            except (ValueError, TypeError, IndexError):
                return ''
        else:
            if key in value:
                value = value[key]
            else:
                return ''
    return default if value in [None, ''] else value


def _rf(cursor, row):
    # https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.row_factory
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


class WotTree():
    def __init__(self):
        # Variables
        self.tld = ''
        self.player = ''
        self.language = ''
        self.account_id = 0

        # Database
        self.db = sqlite3.connect('wot.db')
        self.db.row_factory = _rf
        self.sql = self.db.cursor()

        # Initialize the tables
        if self.sql.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchone() is None:
            for q in ['CREATE TABLE "tanks" ("tank_id" INTEGER NOT NULL, "type" TEXT NOT NULL, "nation" TEXT NOT NULL, "tier" INTEGER NOT NULL, "tag" TEXT NOT NULL, "name" TEXT NOT NULL, "is_premium" TEXT NOT NULL, "is_gift" TEXT NOT NULL, "is_wheeled" TEXT NOT NULL, "hp" INTEGER NOT NULL, "price_xp" INTEGER NOT NULL, "price_credit" INTEGER NOT NULL, "price_gold" INTEGER NOT NULL, "elite_equipment_xp" INTEGER NOT NULL, "elite_equipment_cost" INTEGER NOT NULL, "elite_tanks_xp" INTEGER NOT NULL, "description" TEXT NOT NULL, "url" TEXT NOT NULL, PRIMARY KEY("tank_id"))',
                      'CREATE TABLE "tanks_tree" ("tank_id" INTEGER NOT NULL, "next_tank_id" INTEGER NOT NULL, PRIMARY KEY("next_tank_id","tank_id"))',
                      'CREATE TABLE "players" ("server" TEXT NOT NULL, "account_id" INTEGER NOT NULL, "name" TEXT NOT NULL, PRIMARY KEY("account_id","server"))',
                      'CREATE TABLE "players_tanks" ("server" TEXT NOT NULL, "account_id" INTEGER NOT NULL, "tank_id" INTEGER NOT NULL, "battles" INTEGER NOT NULL, "wins" INTEGER NOT NULL, "mastery" INTEGER NOT NULL, "win_rate" REAL NOT NULL, PRIMARY KEY("tank_id","account_id","server"))']:
                self.sql.execute(q)
            self.db.commit()

    def set_parameters(self, server='', player='', language=''):
        # Default values
        self.tld = server
        self.player = player
        self.language = language

        # Server name
        if self.tld == '':
            print('Name of the server = ', end='')
            self.tld = input().strip().lower()
            if self.tld == 'us':
                self.tld = 'com'

        # Player name
        if self.player == '':
            print('Name of the player = ', end='')
            self.player = input().strip()

        # Language
        if self.language == '':
            print('Language = ', end='')
            self.language = input().strip().lower()
            if self.language == '':
                self.language = 'en'

        # Result
        return self.tld in ['eu', 'com', 'ru', 'asia'] \
            and self.player != '' \
            and self.language in ['en', 'ru', 'pl', 'de', 'fr', 'es', 'zh-cn', 'zh-tw', 'tr', 'cs', 'th', 'vi', 'ko']

    def search_player(self, refresh=False):
        # Query the database
        if not refresh:
            self.sql.execute(''' SELECT account_id
                                 FROM players
                                 WHERE server      = ?
                                   AND LOWER(name) = ? ''',
                             (self.tld, self.player.lower()))
            row = self.sql.fetchone()
            if row is not None:
                self.account_id = row['account_id']
                return True

        # Call the API
        params = {'application_id': APP_ID,
                  'search': self.player,
                  'language': self.language,
                  'limit': 1,
                  'type': 'exact'}
        url = 'https://api.worldoftanks.%s/wot/account/list/?%s' % (self.tld, urlencode(params))
        query = urlopen(Request(url, None, method='GET'))
        if query.status == 200:
            data = query.read().decode('utf-8')
        else:
            return False

        # Parse the data
        data = json.loads(data)
        if (_field(data, 'status') != 'ok') or (len(_field(data, 'data')) != 1):
            return False
        self.account_id = _field(data, 'data/[0]/account_id')

        # Cache the result
        self.sql.execute(''' INSERT OR REPLACE INTO players
                             (server, account_id, name)
                             VALUES (?, ?, ?) ''',
                         (self.tld, self.account_id, self.player))
        self.db.commit()
        return True

    def cache_tanks(self, refresh=False):
        # Connect to the database
        if refresh:
            self.sql.execute('DELETE FROM tanks')
            self.sql.execute('DELETE FROM tanks_tree')
        elif self.sql.execute(''' SELECT tank_id
                                  FROM tanks
                                  LIMIT 1 ''').fetchone() is not None:
            return True
        print('Fetching all the tanks once... (estimated time: 1 minute)')

        # Fetch the tanks by small batches of assumedly less than 100 entries
        tanks = []
        tanks_tree = []
        for tier in range(MAX_TIER):
            for type in ['heavyTank', 'AT-SPG', 'mediumTank', 'lightTank', 'SPG']:
                sleep(1)

                # Call the API
                params = {'application_id': APP_ID,
                          'language': self.language,
                          'tier': tier + 1,
                          'type': type}
                url = 'https://api.worldoftanks.%s/wot/encyclopedia/vehicles/?%s' % (self.tld, urlencode(params))
                query = urlopen(Request(url, None, method='GET'))
                if query.status == 200:
                    data = query.read().decode('utf-8')
                    data = json.loads(data)
                    if _field(data, 'status') != 'ok':
                        return False
                    alldata = data['data']

                    # Analyze each tank
                    for tid in alldata:
                        data = alldata[tid]

                        # Tank main properties
                        entry = {'tank_id': _field(data, 'tank_id', 0),
                                 'type': _field(data, 'type'),
                                 'nation': _field(data, 'nation'),
                                 'tier': _field(data, 'tier', 0),
                                 'tag': _field(data, 'tag'),
                                 'name': _field(data, 'name'),
                                 'is_premium': _bool(_field(data, 'is_premium')),
                                 'is_gift': _bool(_field(data, 'is_gift')),
                                 'is_wheeled': _bool(_field(data, 'is_wheeled')),
                                 'hp': _field(data, 'default_profile/hp'),
                                 'price_xp': 0,
                                 'price_credit': _field(data, 'price_credit', 0),
                                 'price_gold': _field(data, 'price_gold', 0),
                                 'elite_equipment_xp': 0,
                                 'elite_equipment_cost': 0,
                                 'elite_tanks_xp': 0,
                                 'description': _field(data, 'description'),
                                 'url': ''}

                        # Parent tank to deduct tank XP (inaccurate for SU-152 that has 2 parents)
                        subdata = _field(data, 'prices_xp')
                        for nid in subdata:
                            entry['price_xp'] = subdata[nid]
                            break

                        # Modules XP & cost
                        subdata = _field(data, 'modules_tree')
                        for nid in subdata:
                            if not _bool(_field(subdata[nid], 'is_default')):
                                entry['elite_equipment_xp'] += _field(subdata[nid], 'price_xp', 0)
                                entry['elite_equipment_cost'] += _field(subdata[nid], 'price_credit', 0)

                        # Tanks tree
                        subdata = _field(data, 'next_tanks')
                        for nid in subdata:
                            tanks_tree.append((entry['tank_id'], _int(nid)))
                            entry['elite_tanks_xp'] += subdata[nid]

                        # Entry
                        entry['url'] = 'https://worldoftanks.%s/%s/tankopedia/%d-%s/' % (self.tld, self.language, entry['tank_id'], entry['tag'])
                        tanks.append(entry)

        # Save to database
        for entry in tanks:
            self.sql.execute(''' INSERT INTO tanks
                                 (tank_id, type, nation, tier, tag, name, is_premium, is_gift,
                                  is_wheeled, hp, price_xp, price_credit, price_gold,
                                  elite_equipment_xp, elite_equipment_cost, elite_tanks_xp,
                                  description, url)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ''', _o2t(entry))
        for entry in tanks_tree:
            self.sql.execute(''' INSERT INTO tanks_tree
                                 (tank_id, next_tank_id)
                                 VALUES (?, ?) ''', entry)
        self.db.commit()
        return True

    def cache_player(self, refresh=False):
        # Connect to the database
        if self.sql.execute(''' SELECT 1
                                FROM players_tanks
                                WHERE server     = ?
                                    AND account_id = ?
                                LIMIT 1 ''',
                            (self.tld, self.account_id)).fetchone() is not None:
            if refresh:
                self.sql.execute(''' DELETE FROM players_tanks
                                     WHERE server     = ?
                                       AND account_id = ? ''',
                                 (self.tld, self.account_id))
            else:
                return True
        print('Fetching the tanks of the player...')

        # Call the API
        params = {'application_id': APP_ID,
                  'account_id': self.account_id,
                  'language': self.language}
        url = 'https://api.worldoftanks.%s/wot/account/tanks/?%s' % (self.tld, urlencode(params))
        query = urlopen(Request(url, None, method='GET'))
        if query.status == 200:
            data = query.read().decode('utf-8')
            data = json.loads(data)
            if _field(data, 'status') != 'ok':
                return False

            # Analyze each tank
            for entry in data['data'][str(self.account_id)]:
                self.sql.execute(''' INSERT INTO players_tanks
                                     (server, account_id, tank_id, battles, wins, mastery, win_rate)
                                     VALUES (?, ?, ?, ?, ?, ?, 0) ''',
                                 (self.tld,
                                  self.account_id,
                                  _field(entry, 'tank_id'),
                                  _field(entry, 'statistics/battles'),
                                  _field(entry, 'statistics/wins'),
                                  _field(entry, 'mark_of_mastery')))
        self.sql.execute(''' UPDATE players_tanks
                             SET win_rate = ROUND(1000.0 * wins / battles) / 10.
                             WHERE server     = ?
                               AND account_id = ? ''',
                         (self.tld, self.account_id))
        self.db.commit()
        return True

    def generate_graphviz(self, filename, min_played=0, special=True, mastery=True, tier_helper=True):
        # https://graphviz.org/doc/info/lang.html

        # Initialize
        roman = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']  # ['&#x%x;' % i for i in range(0x2160, 0x216A)]

        def _attr2str(obj):
            return ';'.join([' %s = "%s"' % (k, obj[k].replace('"', '\\"')) for k in obj])

        # List of the nations played by the user
        self.sql.execute(''' SELECT DISTINCT b.nation
                             FROM players_tanks AS a
                                 INNER JOIN tanks AS b
                                     ON b.tank_id = a.tank_id
                             WHERE a.server      = ?
                               AND a.account_id  = ?
                               AND a.battles    >= ?
                             ORDER BY nation ''',
                         (self.tld, self.account_id, min_played))
        nations = [row['nation'] for row in self.sql.fetchall()]
        if len(nations) == 0:
            return False
        print('Generating the picture...')

        # List of the tanks owned by the player
        owned_tanks = {}
        self.sql.execute(''' SELECT tank_id, battles, wins, mastery, win_rate
                             FROM players_tanks
                             WHERE server     = ?
                               AND account_id = ?
                             ORDER BY tank_id ''',
                         (self.tld, self.account_id))
        for row in self.sql.fetchall():
            owned_tanks['n%d' % row['tank_id']] = row

        # List of all the tanks
        tanks = {}
        self.sql.execute(''' SELECT tank_id, type, nation, tier, name, is_premium,
                                    price_xp, price_credit, price_gold, elite_equipment_xp,
                                    elite_equipment_cost, elite_tanks_xp, description, url
                             FROM tanks
                             ORDER BY nation, tier, type ''')
        for row in self.sql.fetchall():
            row['type'] = {'AT-SPG': '&#x25BC;',
                           'heavyTank': '&#x25CF;',
                           'lightTank': '&#x2BC1;',
                           'mediumTank': '&#x25C8;',
                           'SPG': '&#x25FC;'}[row['type']]
            tanks['n%d' % row['tank_id']] = row

        # Excluded tanks
        if special:
            self.sql.execute(''' SELECT a.tank_id
                                 FROM tanks AS a
                                     LEFT OUTER JOIN tanks_tree AS b         -- No predecessor
                                         ON b.next_tank_id = a.tank_id
                                     LEFT OUTER JOIN players_tanks AS c      -- Not owned by the player
                                         ON  c.server     = ?
                                         AND c.account_id = ?
                                         AND c.tank_id    = a.tank_id
                                 WHERE a.tier > 1
                                 AND b.tank_id IS NULL
                                 AND c.tank_id IS NULL ''',
                             (self.tld, self.account_id))
        else:
            self.sql.execute(''' SELECT tank_id
                                 FROM tanks
                                 WHERE is_premium = 'X'
                                    OR is_gift    = 'X'
                                    OR price_gold > 0
                                    OR (price_xp == 0 AND tier > 1) ''')
        excluded_tanks = ['n%d' % row['tank_id'] for row in self.sql.fetchall()]

        # Build the graph
        counter = {'battles': 0, 'wins': 0}
        buffer = 'digraph wot {'
        # Bar of the tiers
        if tier_helper:
            buffer += '\n{ node [shape = plaintext; fontsize = 16]; I -> II -> III -> IV -> V -> VI -> VII -> VIII -> IX -> X }'
        # Block of nations
        for nat in nations:
            buffer += '\nsubgraph cluster_%s {' % nat
            buffer += 'label = "%s";' % nat.upper()
            rank_lines = [[] for i in range(MAX_TIER + 1)]
            # Tanks of the nation
            for tid in tanks:
                if tid in excluded_tanks:
                    continue
                t = tanks[tid]
                if t['nation'] == nat:
                    attr = {}
                    attr['label'] = '%s %s %s%s' % (roman[t['tier'] - 1],
                                                    t['type'],
                                                    t['name'],
                                                    ' &#x2605;' if t['is_premium'] else '')
                    if tid in owned_tanks:
                        otid = owned_tanks[tid]
                        attr['label'] += '\\n%d / %d = %.1f %%' % (otid['wins'], otid['battles'], otid['win_rate'])
                        counter['battles'] += otid['battles']
                        counter['wins'] += otid['wins']
                    attr['tooltip'] = 'Tank %s\\n' % tid[1:]
                    if t['price_gold'] + t['price_credit'] == 0:
                        attr['tooltip'] += 'With obligations'
                    elif t['price_gold'] > 0:
                        attr['tooltip'] += 'Gold %d' % t['price_gold']
                    else:
                        attr['tooltip'] += 'Cost = %d (base) + %d (equipments)' % (t['price_credit'], t['elite_equipment_cost'])
                    if t['price_xp'] + t['elite_equipment_xp'] + t['elite_tanks_xp'] > 0:
                        attr['tooltip'] += '\\nXP = %d (base) + %d (equipments) + %d (tanks)' % (t['price_xp'],
                                                                                                 t['elite_equipment_xp'],
                                                                                                 t['elite_tanks_xp'])
                    attr['fontname'] = UNICODE_FONT
                    attr['color'] = 'green' if tid in owned_tanks else 'red'
                    attr['penwidth'] = '2.5'
                    attr['shape'] = 'box'
                    if mastery:
                        ranking = ['', '#CAA236', '#E0E0E0', '#FFFF00', 'green'][_int(owned_tanks[tid]['mastery'])] if tid in owned_tanks else '#FFE1E1'
                        if ranking != '':
                            attr['style'] = 'filled'
                            attr['fillcolor'] = ranking
                    attr['URL'] = t['url']
                    rank_lines[t['tier']].append(tid)
                    buffer += '\n%s [%s];' % (tid, _attr2str(attr))
            # Constrained ranks
            for a in rank_lines:
                if len(a) > 0:
                    buffer += '\n{rank = same; %s}' % ('; '.join(a))
            buffer += '\n}'
        # Tank tree
        self.sql.execute(''' SELECT a.tank_id, a.next_tank_id, b.nation
                             FROM tanks_tree AS a
                                 INNER JOIN tanks AS b
                                     ON b.tank_id = a.tank_id
                             ORDER BY a.tank_id, a.next_tank_id ''')
        for row in self.sql.fetchall():
            if row['nation'] in nations:
                buffer += '\nn%d -> n%d;' % (row['tank_id'], row['next_tank_id'])
        # Title of the graph
        buffer += '\nlabel = <<B>%s\'s tech tree in World of Tanks</B><BR/>%d wins in %d battles (%.1f%%)>;' % \
                  (self.player,
                   counter['wins'],
                   counter['battles'],
                   100.0 * counter['wins'] / counter['battles'])
        # Closure
        buffer += '\n}'

        # Save to output
        if filename in [None, '', '.', '..']:
            sys.stdout.reconfigure(encoding='utf-8')
            print(buffer)
        else:
            try:
                f = open(filename + '.gv', 'w', encoding='utf-8')
                f.write(buffer)
                f.close()
            except Exception:
                return False
        return True

    def generate_picture(self, filename):
        if filename not in [None, '', '.', '..']:
            ext = filename.split('.')[-1].strip().lower()
            if ext in ['png', 'jpg', 'svg', 'ps', 'json']:
                filename = filename.replace('"', '\\"')
                return os.system('dot -T%s "%s.gv" -o "%s"' % (ext, filename, filename)) == 0
        return False


def main():
    # Check the registration
    if len(APP_ID) != 32:
        print('Error: your must register the application first')
        return False

    # Read the command line
    parser = argparse.ArgumentParser(description='World of Tanks - Explore a player\'s tech tree')
    parser.add_argument('--server', default='', help='Realm (ex: eu)')
    parser.add_argument('--player', default='', help='Name of the player (ex: Pamboum)')
    parser.add_argument('--language', default='', help='Language (ex: en)')
    parser.add_argument('--update-tankopedia', action='store_true', help='Force the update of the tankopedia')
    parser.add_argument('--no-cache', action='store_true', help='Refresh the data of the player')
    parser.add_argument('--min-played', type=int, default=0, help='Minimum games played per nation')
    parser.add_argument('--no-special', action='store_true', help='Hide the special tanks out of the tech tree')
    parser.add_argument('--no-mastery', action='store_true', help='Hide the colors of mastery')
    parser.add_argument('--no-tier', action='store_true', help='Hide the left indicator showing the tiers')
    parser.add_argument('filename', default='.', help='Final filename. Use "." for stdout')
    argv = parser.parse_args()
    refresh_tankopedia = argv.update_tankopedia
    refresh_player = argv.no_cache or refresh_tankopedia

    # Build the picture
    result = False
    wot = WotTree()
    if not wot.set_parameters(server=argv.server, player=argv.player, language=argv.language):
        print('Error: invalid parameters')
    else:
        if not wot.search_player(refresh=refresh_player):
            print('Error: player not found')
        else:
            if not wot.cache_tanks(refresh=refresh_tankopedia):
                print('Error: tanks not found')
            else:
                if not wot.cache_player(refresh=refresh_player):
                    print("Error: player's tanks not found")
                else:
                    if wot.generate_graphviz(argv.filename,
                                             min_played=argv.min_played,
                                             special=not argv.no_special,
                                             mastery=not argv.no_mastery,
                                             tier_helper=not argv.no_tier):
                        result = True
                        if wot.generate_picture(argv.filename):
                            print('The picture is generated!')
                        else:
                            print('A problem occurred during the local generation of the picture')
    return result


main()
