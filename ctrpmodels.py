# -*- coding: utf-8 -*-

#!/usr/bin/env python

# This file contains the models for the NDB entries that CTRP uses to store data in
# app engine.  They're here to keep the definitions out of the ranker code.

import webapp2
import datetime
from google.appengine.ext import ndb

class Constants:

    hmname = 'Highmaul'
    brfname = 'Blackrock Foundry'
    hfcname = 'Hellfire Citadel'

    raids = [hmname, brfname, hfcname]

    difficulties = ['normal','heroic','mythic']

    hmbosses = ['Kargath Bladefist','The Butcher','Brackenspore','Tectus','Twin Ogron','Ko\'ragh','Imperator Mar\'gok']
    brfbosses = ['Oregorger','Gruul','The Blast Furnace','Hans\'gar and Franzok','Flamebender Ka\'graz','Kromog','Beastlord Darmac','Operator Thogar','The Iron Maidens','Blackhand']
    hfcbosses = ['Hellfire Assault','The Iron Reaver','Hellfire High Council','Kormrok','Kilrogg Deadeye','The Monstrous Gorefiend','Shadow-Lord Iskar','Fel Lord Zakuun','Xhul\'horac','Socrethar the Eternal','Tyrant Velhari','Mannoroth','Archimonde']

    num_hm_bosses = len(hmbosses)
    num_brf_bosses = len(brfbosses)
    num_hfc_bosses = len(hfcbosses)

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
    hm = ndb.StructuredProperty(Raid, required = True)
    brf = ndb.StructuredProperty(Raid, required = True)
    hfc = ndb.StructuredProperty(Raid, required = True)
    lastupdated = ndb.DateTimeProperty()
    rosterupdated = ndb.DateProperty()
    avgilvl = ndb.IntegerProperty(default = 0)

    # Query used in display.py to get a consistent set of data for both the graphical
    # and text displays.  This is for tier 17 data (HM, BRF)
    @classmethod
    def query_for_t17_display(self):
        q = self.query().order(-Group.brf.mythic, -Group.brf.heroic, -Group.hm.mythic, -Group.brf.normal, -Group.hm.heroic, -Group.hm.normal).order(Group.name)
        results = q.fetch()
        return results

    # Query used in display.py to get a consistent set of data for both the graphical
    # and text displays.  This is for tier 18 data (HFC)
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
    hfc = ndb.StructuredProperty(RaidHistory, required = True)
    brf = ndb.StructuredProperty(RaidHistory, required = True)
    hm = ndb.StructuredProperty(RaidHistory, required = True)
    tweeted = ndb.BooleanProperty(default = False, required = True)

class Mergev1tov2(webapp2.RequestHandler):
    def get(self):
        q = Group.query()
        groups = q.fetch()

        for group in groups:
            # add the hfc raid data
            if group.hfc == None:
                self.response.write('%s: added HFC entry<br/>\n' % group.name)
                group.hfc = Raid()
                group.hfc.raidname = 'Hellfire Citadel'
                group.hfc.bosses = list()
                for boss in Constants.hfcbosses:
                    newboss = Boss(name = boss)
                    group.hfc.bosses.append(newboss)

            if group.brf.bosses == None or len(group.brf.bosses) == 0:
                self.response.write('%s: fixed BRF entry<br/>\n' % group.name)
                group.brf.bosses = list()
                for boss in Constants.brfbosses:
                    newboss = Boss(name = boss)
                    group.brf.bosses.append(newboss)

            if group.hm.bosses == None or len(group.hm.bosses) == 0:
                self.response.write('%s: fixed HM entry<br/>\n' % group.name)
                group.hm.bosses = list()
                for boss in Constants.hmbosses:
                    newboss = Boss(name = boss)
                    group.hm.bosses.append(newboss)

            # remove obsolete fields from the data table
            if 'numbosses' in group.hm._properties:
                del group.hm._properties['numbosses']
                self.response.write('%s: Removed HM numbosses property<br/>\n' % group.name)
            if 'numbosses' in group.brf._properties:
                del group.brf._properties['numbosses']
                self.response.write('%s: Removed BRF numbosses property<br/>\n' % group.name)
            if 'raidname' in group.hm._properties:
                del group.hm._properties['raidname']
                self.response.write('%s: Removed HM raid name property<br/>\n' % group.name)
            if 'raidname' in group.brf._properties:
                del group.brf._properties['raidname']
                self.response.write('%s: Removed BRF raid name property<br/>\n' % group.name)
            if 'rosterupdate' in group._properties:
                del group._properties['rosterupdate']
                self.response.write('%s: Removed rosterupdate property<br/>\n' % group.name)

            # set the rosterupdated field to something in the past so that they
            # all get updated in the next pass through.
            group.rosterupdated = datetime.datetime.strptime('20140101','%Y%m%d').date()
            self.response.write('%s: Updated rosterupdated field to old date<br/>\n' % group.name)

            group.put()
            self.response.write('%s: Done with this group<br/><br/>\n\n' % group.name)
