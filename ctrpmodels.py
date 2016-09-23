# -*- coding: utf-8 -*-

#!/usr/bin/env python

# This file contains the models for the NDB entries that CTRP uses to store data in
# app engine.  They're here to keep the definitions out of the ranker code.

import webapp2
import datetime
import logging
from google.appengine.ext import ndb

class Constants:

    enname = "The Emerald Nightmare"
    nhname = "The Nighthold"

    raids = [enname, nhname]

    enbosses = ['Nythendra','Il\'gynoth, Heart of Corruption','Elerethe Renferal','Ursoc','Dragons of Nightmare','Cenarius','Xavius']
    nhbosses = ['Skorpyron','Chronomatic Anomaly','Trilliax','Spellblade Aluriel','High Botanist Tel\'arn','Star Augur Etraeus','Tichondrius','Krosus','Grand Magistrix Elisande','Gul\'dan']

    num_en_bosses = len(enbosses)
    num_nh_bosses = len(nhbosses)

    difficulties = ['normal','heroic','mythic']

# Model for a single boss in a raid instance.  Keeps track of whether a boss has been
# killed for each of the difficulties.  There will be multiple of these in each Raid
# model below.
class Boss(ndb.Model):
    name = ndb.StringProperty(required = True, indexed = True)
    normaldead = ndb.DateProperty(required = True, default = None)
    heroicdead = ndb.DateProperty(required = True, default = None)
    mythicdead = ndb.DateProperty(required = True, default = None)

# Model of a raid instance.  This keeps track of the number of bosses killed by a raid
# group for a single instance.  Contains a number of kills for each difficulty, built
# from the array of bosses also kept in this model.  There maybe 1-to-many of these in
# each Group model below.
class Raid(ndb.Model):
    # the next three values are the number of kills for each of difficulties, culled
    # from the boss data.
    normal = ndb.IntegerProperty(required = True, default = 0)
    heroic = ndb.IntegerProperty(required = True, default = 0)
    mythic = ndb.IntegerProperty(required = True, default = 0)
    bosses = ndb.StructuredProperty(Boss, repeated = True)

class Group(ndb.Model):
    name = ndb.StringProperty(indexed=True, required = True)
    toons = ndb.StringProperty(repeated=True)

    # TODO: i'd rather this be a list of raids so it's a bit more easy to extend
    # but it makes the queries harder and makes the data stored in the database
    # more opaque
    en = ndb.StructuredProperty(Raid, required = True)
    nh = ndb.StructuredProperty(Raid, required = True)
    lastupdated = ndb.DateTimeProperty()
    rosterupdated = ndb.DateProperty()
    avgilvl = ndb.IntegerProperty(default = 0)

    # Query used in display.py to get a consistent set of data for both the graphical
    # and text displays.  This is for tier 19 data (EN, NH). This is the model for a
    # split tier.
    @classmethod
    def query_for_t19_display(self):
        q = self.query().order(-Group.nh.mythic, -Group.nh.heroic, -Group.en.mythic, -Group.nh.normal, -Group.en.heroic, -Group.en.normal).order(Group.name)
        results = q.fetch()
        return results

    # Query used in display.py to get a consistent set of data for both the graphical
    # and text displays.  This is for tier 18 data (HFC). This is the model for a
    # single-raid tier.
    @classmethod
    def query_for_t18_display(self):
        q = self.query().order(-Group.hfc.mythic, -Group.hfc.heroic, -Group.hfc.normal).order(Group.name)
        results = q.fetch()
        return results

class Global(ndb.Model):
    lastupdated = ndb.DateTimeProperty(auto_now=True)

class RaidHistory(ndb.Model):
    mythic = ndb.StringProperty(repeated=True)
    heroic = ndb.StringProperty(repeated=True)
    normal = ndb.StringProperty(repeated=True)
    mythic_total = ndb.IntegerProperty(default = 0, required = True)
    heroic_total = ndb.IntegerProperty(default = 0, required = True)
    normal_total = ndb.IntegerProperty(default = 0, required = True)

class History(ndb.Model):
    group = ndb.StringProperty(required = True)
    date = ndb.DateProperty(required = True)
    en = ndb.StructuredProperty(RaidHistory, required = True)
    nh = ndb.StructuredProperty(RaidHistory, required = True)
    tweeted = ndb.BooleanProperty(default = False, required = True)

class MigrateT18toT19(webapp2.RequestHandler):
    def get(self):
        q = Group.query()
        groups = q.fetch()

        for group in groups:
            if 'hfc' in group._properties:
                del group._properties['hfc']
            if 'brf' in group._properties:
                del group._properties['brf']
            if 'hm' in group._properties:
                del group._properties['hm']

            group.nh = Raid()
            group.nh.raidname = Constants.nhname
            group.nh.bosses = list()
            for boss in Constants.nhbosses:
                newboss = Boss(name = boss)
                group.nh.bosses.append(newboss)

            group.en = Raid()
            group.en.raidname = Constants.enname
            group.en.bosses = list()
            for boss in Constants.enbosses:
                newboss = Boss(name = boss)
                group.en.bosses.append(newboss)

            logging.info(group)

            group.put()
