# -*- coding: utf-8 -*-

#!/usr/bin/env python

# This file contains the models for the NDB entries that CTRP uses to store data in
# app engine.  They're here to keep the definitions out of the ranker code.

import logging
from google.cloud import datastore
from datetime import datetime

class Constants(object):

    nyaname = "Ny'alotha, the Waking City"
    nyabosses = ["Wrathion, the Black Emperor", "Maut", "The Prophet Skitra", "Dark Inquisitor Xanesh", "The Hivemind", "Shad'har the Insatiable", "Drest'agath", "Vexiona", "Ra-den the Despoiled", "Il'gynoth, Corruption Reborn", "Carapace of N'Zoth", "N'Zoth the Corruptor"]

    difficulties = ['Mythic', 'Heroic', 'Normal']

    raidnames = [nyaname]
    
    raids = [
        {
            'slug': 'nya',
            'name': nyaname,
            'bosses': nyabosses
        }
    ]

    # The Blizzard API data from the /encounters/raids API returns the raids
    # broken down by expansion first. This is a constant for finding the
    # right one in the array.
    expansion = 'Battle for Azeroth'
    max_level = 120

def create_new_group(name, roster):
    group = {
        'group': name,
        'normalized': normalize(name).lower(),
        'updated': datetime.now(),
        'toons': roster,
        'avgilvl': 0,
        'raids': {},
        'has_kills': False,
        'had_kills_last_tier': False
    }

    reset_group(group)
    return group

def reset_group(group):
    group['raids'] = build_raid_arrays(group.get('raids', {}))
    group['had_kills_last_tier'] = group['has_kills']

def build_raid_arrays(existing = {}):
    arrays = {}
    for raid in Constants.raids:
        slug = raid.get('slug', '')

        if slug in existing:
            arrays[slug] = existing[slug]
        else:
            arrays[slug] = {}
            for d in Constants.difficulties:
                arrays[slug][d] = [None] * len(raid.get('bosses',[]))
                
    return arrays

def normalize(groupname):
    return groupname.lower().replace('\'', '').replace(' ', '-').replace('"', '')

def get_sort_key(group):
    raids = group.get('raids', [])
    
    if len(raids) == 1:
        
        slug = Constants.raids[0].get('slug', '')
        raid = raids.get(slug, {})
        boss_count = len(raid.get('Mythic',[]))
        return '{:02d}-{:02d}-{:02d}'.format(boss_count - raid.get('Mythic', []).count(None),
                                             boss_count - raid.get('Heroic', []).count(None),
                                             boss_count - raid.get('Normal', []).count(None))
    
    elif len(raids) == 2:

        slug0 = Constants.raids[0].get('slug', '')
        slug1 = Constants.raids[1].get('slug', '')
        raid0 = raids.get(slug0, {})
        raid1 = raids.get(slug1, {})
        
        boss_count_0 = len(raid0.get('Mythic',[]))
        boss_count_1 = len(raid1.get('Mythic',[]))
        return '{:02d}-{:02d}-{:02d}-{:02d}-{:02d}-{:02d}'.format(
            boss_count_1 - raid1.get('Mythic', []).count(None),
            boss_count_1 - raid1.get('Heroic', []).count(None),
            boss_count_0 - raid0.get('Mythic', []).count(None),
            boss_count_1 - raid1.get('Normal', []).count(None),
            boss_count_0 - raid0.get('Heroic', []).count(None),
            boss_count_0 - raid0.get('Normal', []).count(None))
