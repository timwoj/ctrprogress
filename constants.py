# -*- coding: utf-8 -*-

#!/usr/bin/env python

# This file contains the models for the NDB entries that CTRP uses to store data in
# app engine.  They're here to keep the definitions out of the ranker code.

import logging
from google.cloud import datastore

class Constants(object):

    nyaname = "Ny'alotha, The Waking City"
    nyabosses = ["Wrathion, the Black Emperor", "Maut", "The Prophet Skitra", "Dark Inquisitor Xanesh", "The Hivemind", "Shad'har the Insatiable", "Drest'agath", "Vexiona", "Ra-den the Despoiled", "Il'gynoth, Corruption Reborn", "Carapace of N'Zoth", "N'Zoth, the Corruptor"]

    difficulties = ['normal', 'heroic', 'mythic']

    raidnames = [nyaname]
    raids = [('nya', nyaname, nyabosses)]
