# -*- coding: utf-8 -*-
#!/usr/bin/env python

import webapp2,jinja2,os,datetime
import ctrpmodels

def normalize(groupname):
    return groupname.lower().replace('\'','').replace(' ','-').replace('"','')

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])
JINJA_ENVIRONMENT.filters['normalize'] = normalize

class Display(webapp2.RequestHandler):
    def get(self):

        q = ctrpmodels.Global.query()
        r = q.fetch()
        template_values = {
            'last_updated': datetime.datetime.now(),
            'title' : 'Main',
            'tier': 22
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        self.response.write('<table>\n')

        groups = ctrpmodels.Group.query_for_singletier_display()
        for group in groups:
            template_values = {'group' : group}
            template = JINJA_ENVIRONMENT.get_template('templates/group-raids.html')
            self.response.write(template.render(template_values))

        self.response.write('</table>\n')

        template_values = {}
        template = JINJA_ENVIRONMENT.get_template('templates/footer.html')
        self.response.write(template.render(template_values))

    def build_tooltips(self):

        self.response.content_type = 'application/javascript'
        self.response.write('$(function() {\n')
        self.response.write('$(document).tooltip({\n')
        self.response.write('items: "[ttid]",\n')
        self.response.write('content: function() {\n')
        self.response.write('var tooltips = {};\n')
        
        groups = ctrpmodels.Group.query_for_singletier_display()
        for raidinfo in ctrpmodels.Constants.raids:
            raid = raidinfo[0]
            for group in groups:
                normaltext = ""
                heroictext = ""
                mythictext = ""
                bosses = []
                groupraid = getattr(group, raid)
                raidbosses = getattr(ctrpmodels.Constants, raid+'bosses')
                
                for boss in groupraid.bosses:
                    bosses.append((boss.name, boss.normaldead, boss.heroicdead, boss.mythicdead))
                index_dict = {item: index for index, item in enumerate(raidbosses)}
                bosses.sort(key=lambda t:index_dict[t[0]])

                for boss in bosses:
                    if boss[1] != None:
                        normaltext += "<div class='bossdead'>"+boss[0]+"</div>";
                    else:
                        normaltext += "<div class='bossalive'>"+boss[0]+"</div>";
                    if boss[2] != None:
                        heroictext += "<div class='bossdead'>"+boss[0]+"</div>";
                    else:
                        heroictext += "<div class='bossalive'>"+boss[0]+"</div>";
                    if boss[3] != None:
                        mythictext += "<div class='bossdead'>"+boss[0]+"</div>";
                    else:
                        mythictext += "<div class='bossalive'>"+boss[0]+"</div>";

                template_values = {
                    'name': group.name,
                    'raid': raid,
                    'normaltext': normaltext,
                    'heroictext': heroictext,
                    'mythictext': mythictext,
                }
                template = JINJA_ENVIRONMENT.get_template('templates/group-tooltip.js')
                self.response.write(template.render(template_values))
                
        self.response.write('\n');
        self.response.write('var element = $(this);\n')
        self.response.write('var ttid = element.attr("ttid");\n')
        self.response.write('return tooltips[ttid];\n')
        self.response.write('}});\n')
        self.response.write('});\n')

class DisplayHistory(webapp2.RequestHandler):
    def get(self):
        groupname = self.request.get('group')
        print groupname
        if (groupname == None or len(groupname) == 0):
            self.displayFullHistory()
        else:
            self.displayGroup(groupname)

    def displayFullHistory(self):
        q = ctrpmodels.Global.query()
        r = q.fetch()

        lastupdated = r[0].lastupdated
#        lastupdated = datetime.datetime.now()

        template_values = {
            'last_updated': lastupdated,
            'title' : 'History'
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        # add the beginnings of the table
        self.response.write('<table style="margin-left:50px;margin-right:50px">\n')

        # request all of the history entries, sorted in reverse order by date
        curdate = datetime.date.today()
        oneday = datetime.timedelta(1)

        # this is a time object at 2AM AZ time (or 9AM UTC)
        az2am = datetime.time(9)

        for i in xrange(0,13):
            self.response.write('<tr><td colspan="2" class="history-date">'+str(curdate)+'</td></tr>\n')

            # Retrieve all of the entires for this date ordered by group name
            q = ctrpmodels.History.query(ctrpmodels.History.date == curdate).order(ctrpmodels.History.group)
            updates = q.fetch()
            if (len(updates) == 0):
                # if there were no results for this date, add just a simple
                # entry displaying nothing
                self.response.write('<tr>')

                self.response.write('<td colspan="2" style="text-align:center">')
                if (i == 0):
                    current = datetime.datetime.now()
                    if (current > lastupdated):
                        self.response.write('Data not parsed for today yet')
                    else:
                        self.response.write('No new kills for this date!')
                else:
                    self.response.write('No new kills for this date!')
                self.response.write('</td>')
                self.response.write('</tr>\n')
                
            else:

                # now loop through the groups and output the updates in some
                # fashion
                for u in updates:

                    template_values = {
                        'history': u,
                        'num_uldir_bosses': len(ctrpmodels.Constants.uldirbosses)
                    }
                    template = JINJA_ENVIRONMENT.get_template(
                        'templates/history.html')
                    self.response.write(template.render(template_values))
                    self.response.write('\n')

            curdate -= oneday

        self.response.write('</table>\n')
        template_values = {}
        template = JINJA_ENVIRONMENT.get_template('templates/footer.html')
        self.response.write(template.render(template_values))

    def displayGroup(self, groupname):
        q = ctrpmodels.Global.query()
        r = q.fetch()

        lastupdated = r[0].lastupdated
#        lastupdated = datetime.datetime.now()

        template_values = {
            'last_updated': lastupdated,
            'title' : 'History'
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        # Record all history for this group that has been recorded sorted by the
        # date
        q = ctrpmodels.History.query(ctrpmodels.History.group == groupname).order(-ctrpmodels.History.date)
        entries = q.fetch()

        if (len(entries) == 0):
            self.response.write('No history recorded for group %s' % groupname)
        else:
            self.response.write('<div class="history-date">%s</div><p/>' % groupname)
            # add the beginnings of the table
            self.response.write('<table style="margin-left:50px;margin-right:50px">\n')

            for u in entries:
                template_values = {
                    'history': u,
                    'num_uldir_bosses': len(ctrpmodels.Constants.uldirbosses)
                }
                template = JINJA_ENVIRONMENT.get_template(
                    'templates/group-history.html')
                self.response.write(template.render(template_values))
                self.response.write('\n')

            self.response.write('</table>\n')
            
        template_values = {}
        template = JINJA_ENVIRONMENT.get_template('templates/footer.html')
        self.response.write(template.render(template_values))

class DisplayTier(webapp2.RequestHandler):
    def get(self, tier_number):
        template_values = {
            'title' : 'Tier %s' % tier_number,
            'tier': tier_number
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        template_values = {}
        template = JINJA_ENVIRONMENT.get_template('templates/tier%s.html' % tier_number)
        self.response.write(template.render(template_values))

        template_values = {}
        template = JINJA_ENVIRONMENT.get_template('templates/footer.html')
        self.response.write(template.render(template_values))
