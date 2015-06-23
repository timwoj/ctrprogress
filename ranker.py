# -*- coding: utf-8 -*-

#!/usr/bin/env python

# External imports
import webapp2,jinja2,os,datetime,json,time
import logging
import twitter

# Imports from google
from google.appengine.ext import ndb
from google.appengine.api.memcache import Client
from google.appengine.api import taskqueue
from google.appengine.api.taskqueue import Queue
from google.appengine.api.taskqueue import QueueStatistics
from google.appengine.api.taskqueue import Task

# Internal imports
import wowapi
from ctrpmodels import Constants
from ctrpmodels import Group
import ctrpmodels

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

class ProgressBuilder(webapp2.RequestHandler):

    def post(self):
        groupname = self.request.get('group')
        if groupname == 'ctrp-taskcheck':

            # Grab the default queue and keep checking for whether or not
            # all of the tasks have finished.
            default_queue = Queue()
            stats = default_queue.fetch_statistics()
            while stats.tasks > 0:
                logging.info("task check: waiting for %d tasks to finish" % stats.tasks)
                time.sleep(5)
                stats = default_queue.fetch_statistics()

            self.finishBuilding()

        else:
            importer = wowapi.Importer()

            q = Group.query(Group.name == groupname)
            groups = q.fetch()
            # sanity check, tho this shouldn't be possible
            if len(groups) == 0:
                logging.info('Builder failed to find group %s' % groupname)
                return

            logging.info('Builder task for %s started' % groupname)
            self.processGroup(groups[0], importer, True)
            logging.info('Builder task for %s completed' % groupname)

    def processGroup(self, group, importer, writeDB):
        logging.info('Starting work on group %s' % group.name)

        data = list()
        importer.load(group.toons, data)

        progress = dict()
        self.parse(Constants.hfcbosses, data, Constants.hfcname, progress, writeDB)

        # calculate the avg ilvl values from the toon data
        group.avgilvl = 0
        numtoons = 0
        for toon in data:
            # ignore toons that we didn't get data back for or for toons less than
            # level 100
            if 'items' in toon and toon['level'] == 100:
                numtoons += 1
                group.avgilvl += toon['items']['averageItemLevel']

        if numtoons != 0:
            group.avgilvl /= numtoons

        self.response.write(group.name + " data generated<br/>")

        # update the entry in ndb with the new progression data for this
        # group.  this also checks to make sure that the progress only ever
        # increases, in case of weirdness with the data.  also generate
        # history data while we're at it.
        new_hist = None

        # Loop through the raids that are being processed for this tier and
        # build all of the points of data that are needed.  First, update which
        # bosses have been killed for a group, then loop through the
        # difficulties and build the killed counts and the history.
        for raid in [('hfc',Constants.hfcname,Constants.hfcbosses)]:

            group_raid = getattr(group, raid[0])
            data_raid = progress[raid[1]]

            killedtoday = dict()
            killedtoday['normal'] = list()
            killedtoday['heroic'] = list()
            killedtoday['mythic'] = list()

            for group_boss in group_raid.bosses:
                data_boss = [b for b in data_raid if b.name == group_boss.name][0]
                if data_boss.normaldead != None and group_boss.normaldead == None:
                    killedtoday['normal'].append(data_boss.name)
                    group_boss.normaldead = data_boss.normaldead
                    logging.debug('new normal kill of %s' % data_boss.name)
                if data_boss.heroicdead != None and group_boss.heroicdead == None:
                    killedtoday['heroic'].append(data_boss.name)
                    group_boss.heroicdead = data_boss.heroicdead
                    logging.debug('new heroic kill of %s' % data_boss.name)
                if data_boss.mythicdead != None and group_boss.mythicdead == None:
                    killedtoday['mythic'].append(data_boss.name)
                    group_boss.mythicdead = data_boss.mythicdead
                    logging.debug('new mythic kill of %s' % data_boss.name)

            for d in Constants.difficulties:
                old = getattr(group_raid, d)
                new = len([b for b in group_raid.bosses if getattr(b, d+'dead') != None])
                if old < new:
                    if (new_hist == None):
                        new_hist = ctrpmodels.History(group=group.name)
                        new_hist.date = datetime.date.today()
                        new_hist.hm = ctrpmodels.RaidHistory()
                        new_hist.hm.mythic = list()
                        new_hist.hm.heroic = list()
                        new_hist.hm.normal = list()
                        new_hist.brf = ctrpmodels.RaidHistory()
                        new_hist.brf.mythic = list()
                        new_hist.brf.heroic = list()
                        new_hist.brf.normal = list()
                        new_hist.hfc = ctrpmodels.RaidHistory()
                        new_hist.hfc.mythic = list()
                        new_hist.hfc.heroic = list()
                        new_hist.hfc.normal = list()
                        
                    raidhist = getattr(new_hist, raid[0])

                    raiddiff = getattr(raidhist, d)
                    raiddiff = killedtoday[d]

                    # These aren't necessary unless a new object is created above
                    setattr(raidhist, d+'_total', new)
                    setattr(raidhist, d, raiddiff)
                    setattr(new_hist, raid[0], raidhist)

                    setattr(group_raid, d, new)

        if writeDB:
            group.put()
            if new_hist != None:
                new_hist.put()

        logging.info('Finished building group %s' % group.name)

    def parse(self, bosses, toondata, raidname, progress, writeDB):

        progress[raidname] = list()

        bossdata = dict()
        for boss in bosses:
            bossdata[boss] = dict()
            for d in Constants.difficulties:
                bossdata[boss][d] = dict()
                bossdata[boss][d]['times'] = list()
                bossdata[boss][d]['timeset'] = set()

        # loop through each toon in the data from the blizzard API
        for toon in toondata:

            if 'progression' not in toon:
                continue

            # get just the raid data for this toon
            raids = toon['progression']['raids']

            # this filters the raid data down to just the raid we're looking
            # at this pass
            raid = [d for d in raids if d['name'] == raidname][0]

            # loop through the individual bosses and get the timestamp for
            # the last kill for this toon for each boss
            for boss in bosses:

                # this filters the raid data down to just a single boss
                b = [d for d in raid['bosses'] if d['name'] == boss][0]

                # loop through each difficulty level and grab each timestamp.
                # skip any timestamps of zero.  that means the toon never
                # killed the boss.
                for d in Constants.difficulties:
                    if b[d+'Timestamp'] != 0:
                        bossdata[boss][d]['times'].append(b[d+'Timestamp'])
                        bossdata[boss][d]['timeset'].add(b[d+'Timestamp'])

        # loop back through the difficulties and bosses and build up the
        # progress data
        for boss in bosses:

            bossobj = ctrpmodels.Boss(name = boss)

            for d in Constants.difficulties:
                # for each boss, grab the set of unique timestamps and sort it
                # with the last kill first
                timelist = list(bossdata[boss][d]['timeset'])
                timelist.sort(reverse=True)
                logging.info("kill times for %s %s: %s" % (d, boss, str(timelist)))

                for t in timelist:
                    count = bossdata[boss][d]['times'].count(t)
                    logging.info('%s: time: %d   count: %s' % (boss, t, count))
                    if count >= 5:
                        logging.info('*** found valid kill for %s %s at %d' % (d, boss, t))
                        setattr(bossobj, d+'dead', datetime.date.today())
                        break

            progress[raidname].append(bossobj)

    def finishBuilding(self):

        # update the last updated for the whole dataset.  don't actually
        # have to set the time here, the auto_now flag on the property does
        # it for us.
        q = ctrpmodels.Global.query()
        r = q.fetch()
        if (len(r) == 0):
            g = ctrpmodels.Global()
        else:
            g = r[0]
            g.put()

        # post any changes that happened with the history to twitter
        curdate = datetime.date.today()

        # query for all of the history updates for today that haven't been
        # tweeted yet sorted by group name
        q = ctrpmodels.History.query(ndb.AND(ctrpmodels.History.date == curdate,
                                             ctrpmodels.History.tweeted == False)).order(ctrpmodels.History.group)
        updates = q.fetch()
        
        if len(updates) != 0:
            path = os.path.join(os.path.split(__file__)[0],'api-auth.json')
            json_data = json.load(open(path))

            tw_client = twitter.Api(
                consumer_key=json_data['twitter_consumer_key'],
                consumer_secret=json_data['twitter_consumer_secret'],
                access_token_key=json_data['twitter_access_token'],
                access_token_secret=json_data['twitter_access_secret'],
                cache=None)

            template = 'CtR group <%s> killed %d new boss(es) in %s %s to be %d/%d%s!'
            template_start = 'CtR group <%s> killed %d new boss'
            template_end = ' in %s %s to be %d/%d%s!'
            for u in updates:

                # mark this update as tweeted to avoid reposts
                u.tweeted = True

                for raid in [('hfc',Constants.hfcname,Constants.hfcbosses),
                             ('brf',Constants.brfname,Constants.brfbosses),
                             ('hm',Constants.hmname,Constants.hmbosses)]:

                    raidhist=getattr(u, raid[0])
                    if raidhist != None:
                        for d in reversed(Constants.difficulties):
                            
                            kills = getattr(raidhist, d)
                            total = getattr(raidhist, d+'_total')
                            if len(kills) != 0:
                                text = template_start % (u.group, len(kills))
                                if len(kills) > 1:
                                    text += "es"
                                text+= template_end % (d.title(), raid[1], total,
                                                       len(raid[2]), d.title()[0])
                                if (d != 'normal') and total == len(raid[2]):
                                    text = text + ' #aotc'
                                print text
                                tw_client.PostUpdate(text)

                # update the entry in the database so that the tweeted flag
                # gets set to true
                u.put()

    def loadone(self):
        group = self.request.get('group')
        logging.info('loading single %s' % group)
        q = Group.query(Group.name == group)
        groups = q.fetch()
        logging.info('found %d groups with that name' % len(groups))
        if (len(groups) != 0):
            importer = wowapi.Importer()
            self.processGroup(groups[0], importer, False)

class Ranker(webapp2.RequestHandler):

    def get(self):
        queue = Queue()
        stats = queue.fetch_statistics()

        template_values={
            'tasks': stats.tasks,
            'in_flight': stats.in_flight,
        }
        template = JINJA_ENVIRONMENT.get_template('templates/ranker.html')
        self.response.write(template.render(template_values))

    def post(self):

        # refuse to start the tasks if there are some already running
        queue = Queue()
        stats = queue.fetch_statistics()
        if stats.tasks == 0:

            # queue up all of the groups into individual tasks.  the configuration
            # in queue.yaml only allows 10 tasks to run at once.  the builder only
            # allows 10 URL requests at a time, which should hopefully keep the
            # Blizzard API queries under control.
            q = Group.query()
            groups = q.fetch()
            for g in groups:
                taskqueue.add(url='/builder', params={'group':g.name})

            checker = Task(url='/builder', params={'group':'ctrp-taskcheck'})
            taskcheck = Queue(name='taskcheck')
            taskcheck.add(checker)

        self.redirect('/rank')

class Test(webapp2.RequestHandler):
    def get(self):
        importer = wowapi.Importer()

        q = Group.query(Group.name == 'Raided-X')
        groups = q.fetch()

        if len(groups) != 0:

            data = list()
            importer.load(group.toons, data)

            progress = dict()
            rank = ProgressBuilder()
            rank.parse(Constants.difficulties, Constants.hfcbosses,
                       data, Constants.hfcname, progress)
            logging.info("Finished parsing data")

            logging.info(progress)
