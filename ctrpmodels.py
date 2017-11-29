# -*- coding: utf-8 -*-

#!/usr/bin/env python

# This file contains the models for the NDB entries that CTRP uses to store data in
# app engine.  They're here to keep the definitions out of the ranker code.

import webapp2
import datetime
import logging
from google.appengine.ext import ndb

class Constants:

    antorusname = "Antorus, the Burning Throne"
    raids = [antorusname]

    antorusbosses = ['Garothi Worldbreaker','Felhounds of Sargeras','Antoran High Command','Portal Keeper Hasabel','Eonar the Life-Binder','Imonar the Soulhunter','Kin\'garoth','Varimathras','The Coven of Shivarra','Aggramar','Argus the Unmaker']

    num_antorus_bosses = len(antorusbosses)

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
    antorus = ndb.StructuredProperty(Raid, required = True)
    lastupdated = ndb.DateTimeProperty()
    rosterupdated = ndb.DateProperty()
    avgilvl = ndb.IntegerProperty(default = 0)

    # Query used in display.py to get a consistent set of data for both the graphical
    # and text displays.  This is for tier 21 data (Antorus).. This is the model for a
    # single-raid tier.
    @classmethod
    def query_for_t21_display(self):
        q = self.query().order(-Group.antorus.mythic, -Group.antorus.heroic, -Group.antorus.normal).order(Group.name)
        results = q.fetch()
        return results

    # Query used in display.py to get a consistent set of data for both the graphical
    # and text displays.  This is for tier 19 data (EN, NH). This is the model for a
    # split tier.
    @classmethod
    def query_for_t19_display(self):
        q = self.query().order(-Group.nh.mythic, -Group.nh.heroic, -Group.tov.mythic, -Group.en.mythic, -Group.nh.normal, -Group.tov.heroic, -Group.en.heroic, -Group.tov.normal, -Group.en.normal).order(Group.name)
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
    antorus = ndb.StructuredProperty(RaidHistory, required = True)
    tweeted = ndb.BooleanProperty(default = False, required = True)

class MigrateT20toT21(webapp2.RequestHandler):
    def get(self):
        q = Group.query()
        groups = q.fetch()

        for group in groups:
            if 'tomb' in group._properties:
                del group._properties['tomb']

            group.antorus = Raid()
            group.antorus.raidname = Constants.antorusname
            group.antorus.bosses = list()
            for boss in Constants.antorusbosses:
                newboss = Boss(name = boss)
                group.antorus.bosses.append(newboss)

            logging.info(group)
            group.put()

class MigrateT19toT20(webapp2.RequestHandler):
    def get(self):
        q = Group.query()
        groups = q.fetch()

        for group in groups:
            if 'en' in group._properties:
                del group._properties['en']
            if 'nh' in group._properties:
                del group._properties['nh']
            if 'tov' in group._properties:
                del group._properties['tov']

            group.tomb = Raid()
            group.tomb.raidname = Constants.tombname
            group.tomb.bosses = list()
            for boss in Constants.tombbosses:
                newboss = Boss(name = boss)
                group.tomb.bosses.append(newboss)

            logging.info(group)
            group.put()

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

class MigrateAddToV(webapp2.RequestHandler):
    def get(self):
        q = Group.query()
        groups = q.fetch()

        for group in groups:
            group.tov = Raid()
            group.tov.raidname = Constants.tovname
            group.tov.bosses = list()
            for boss in Constants.tovbosses:
                logging.info(boss)
                newboss = Boss(name = boss)
                group.tov.bosses.append(newboss)

            logging.info(group)

            group.put()

        q = History.query()
        histories = q.fetch()
        for hist in histories:
            hist.tov = RaidHistory()
            hist.tov.mythic = list()
            hist.tov.heroic = list()
            hist.tov.normal = list()
            hist.put()
