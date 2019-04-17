# -*- coding: utf-8 -*-

#!/usr/bin/env python

# This file contains the models for the NDB entries that CTRP uses to store data in
# app engine.  They're here to keep the definitions out of the ranker code.

import logging
from google.appengine.ext import ndb

class Constants(object):

    bodname = "Battle of Dazar'alor"
    bodbosses = ["Champion of the Light", "Jadefire Masters", "Grong, the Revenant", "Opulence", "Conclave of the Chosen", "King Rastakhan", "High Tinker Mekkatorque", "Stormwall Blockade", "Lady Jaina Proudmoore"]

    difficulties = ['normal', 'heroic', 'mythic']

    raidnames = [bodname]
    raids = [('bod', bodname, bodbosses)]

# Model for a single boss in a raid instance.  Keeps track of whether a boss has been
# killed for each of the difficulties.  There will be multiple of these in each Raid
# model below.
class Boss(ndb.Model):
    name = ndb.StringProperty(required=True, indexed=True)
    normaldead = ndb.DateProperty(required=True, default=None)
    heroicdead = ndb.DateProperty(required=True, default=None)
    mythicdead = ndb.DateProperty(required=True, default=None)

# Model of a raid instance.  This keeps track of the number of bosses killed by a raid
# group for a single instance.  Contains a number of kills for each difficulty, built
# from the array of bosses also kept in this model.  There maybe 1-to-many of these in
# each Group model below.
class Raid(ndb.Model):
    # the next three values are the number of kills for each of difficulties, culled
    # from the boss data.
    normal = ndb.IntegerProperty(required=True, default=0)
    heroic = ndb.IntegerProperty(required=True, default=0)
    mythic = ndb.IntegerProperty(required=True, default=0)
    bosses = ndb.StructuredProperty(Boss, repeated=True)

class Group(ndb.Model):
    name = ndb.StringProperty(indexed=True, required=True)
    toons = ndb.StringProperty(repeated=True)

    # TODO: i'd rather this be a list of raids so it's a bit more easy to extend
    # but it makes the queries harder and makes the data stored in the database
    # more opaque
    bod = ndb.StructuredProperty(Raid, required=True)
    lastupdated = ndb.DateTimeProperty()
    rosterupdated = ndb.DateProperty()
    avgilvl = ndb.IntegerProperty(default=0)

    # Query used in display.py to get a consistent set of data for both the graphical
    # and text displays.
    @classmethod
    def query_for_singletier_display(cls):
        query = cls.query().order(-Group.bod.mythic, -Group.bod.heroic, -Group.bod.normal).order(Group.name)
        results = query.fetch()
        return results

    # Query used in display.py to get a consistent set of data for both the graphical
    # and text displays.
    @classmethod
    def query_for_splittier_display(cls):
        query = cls.query().order(-Group.nh.mythic, -Group.nh.heroic, -Group.tov.mythic, -Group.en.mythic, -Group.nh.normal, -Group.tov.heroic, -Group.en.heroic, -Group.tov.normal, -Group.en.normal).order(Group.name)
        results = query.fetch()
        return results

    @classmethod
    def get_group_by_name(cls, group_name):
        results = cls.query(cls.name == group_name).fetch(1)
        if results:
            return results[0]
        return None

class Global(ndb.Model):
    lastupdated = ndb.DateTimeProperty(auto_now=True)

    @classmethod
    def get_last_updated(cls):
        result = cls.query().fetch()
        if result:
            updated = result[0].lastupdated
            return updated
        return None

class RaidHistory(ndb.Model):
    mythic = ndb.StringProperty(repeated=True)
    heroic = ndb.StringProperty(repeated=True)
    normal = ndb.StringProperty(repeated=True)
    mythic_total = ndb.IntegerProperty(default=0, required=True)
    heroic_total = ndb.IntegerProperty(default=0, required=True)
    normal_total = ndb.IntegerProperty(default=0, required=True)

class History(ndb.Model):
    group = ndb.StringProperty(required=True)
    date = ndb.DateProperty(required=True)
    bod = ndb.StructuredProperty(RaidHistory, required=True)
    tweeted = ndb.BooleanProperty(default=False, required=True)

    @classmethod
    def get_for_date(cls, date):
        results = cls.query(cls.date == date).order(cls.group).fetch()
        return results

    @classmethod
    def get_for_group(cls, group_name):
        results = cls.query(cls.group == group_name).order(-cls.date)
        return results

    @classmethod
    def get_not_tweeted(cls, date):
        results = cls.query(ndb.AND(cls.date == date,
                                    cls.tweeted == False)).order(cls.group)
        return results

def migrate():
    groups = Group.query().fetch()
    for group in groups:
        if 'uldir' in group._properties:
            del group._properties['uldir']

        group.bod = Raid()
        group.bod.raidname = Constants.bodname
        group.bod.bosses = list()
        for boss in Constants.bodbosses:
            newboss = Boss(name=boss)
            group.bod.bosses.append(newboss)

        logging.info(group)
        group.put()
