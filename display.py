# -*- coding: utf-8 -*-
#!/usr/bin/env python

import webapp2,jinja2,os,datetime
import ctrpmodels

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

class Display(webapp2.RequestHandler):
    def get(self):

        q = ctrpmodels.Global.query()
        r = q.fetch()
        template_values = {
            'last_updated': datetime.datetime.now(),
            'title' : 'Main'
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        # get the group data from the datastore, and order it in decreasing order
        # so that further progressed teams show up first.  break ties by
        # alphabetical order of group names
        groups = ctrpmodels.Group.query_for_t17_display()

        for group in groups:
            template_values = {'group' : group}
            template = JINJA_ENVIRONMENT.get_template('templates/group.html')
            self.response.write(template.render(template_values))

        template_values = {}
        template = JINJA_ENVIRONMENT.get_template('templates/footer.html')
        self.response.write(template.render(template_values))

class DisplayText(webapp2.RequestHandler):
    def get(self):

        q = ctrpmodels.Global.query()
        r = q.fetch()

        template_values = {
            'last_updated': datetime.datetime.now(),
            'title' : 'Text Display'
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        # get the group data from the datastore, and order it in decreasing order
        # so that further progressed teams show up first.  break ties by
        # alphabetical order of group names
        groups = ctrpmodels.Group.query_for_t17_display()

        for group in groups:
            self.response.write('%s (Avg ilvl: %d)<br/>' % (group.name,group.avgilvl))
            self.writeProgress(group.brf)
            self.writeProgress(group.hm)
            self.response.write('<br/>')
        template_values = {}
        template = JINJA_ENVIRONMENT.get_template('templates/footer.html')
        self.response.write(template.render(template_values))

    def writeProgress(self, raid):
        self.response.write("%s: %d/%dN %d/%dH %d/%dM<br/>" %
                        (raid.raidname, raid.normal, raid.numbosses,
                         raid.heroic, raid.numbosses, raid.mythic,
                         raid.numbosses))

class DisplayHistory(webapp2.RequestHandler):
    def get(self):
        q = ctrpmodels.Global.query()
        r = q.fetch()

        lastupdated = r[0].lastupdated

        template_values = {
            'last_updated': r[0].lastupdated,
            'title' : 'History'
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        # add the beginnings of the table
        self.response.write('<table>')

        # request all of the history entries, sorted in reverse order by date
        curdate = datetime.date.today()
        oneday = datetime.timedelta(1)

        # this is a time object at 2AM AZ time (or 9AM UTC)
        az2am = datetime.time(9)

        for i in range(0,13):
            self.response.write('<thead><tr>\n')
            self.response.write('<th colspan="2" style="padding-top:20px">'+str(curdate)+'</th>\n')
            self.response.write('</tr></thead>\n')
            q = ctrpmodels.History.query(ctrpmodels.History.date == curdate)
            r = q.fetch()
            if (len(r) == 0):
                # if there were no results for this date, add just a simple
                # entry displaying nothing
                self.response.write('<tr>\n')

                self.response.write('<td colspan="2" style="text-align:center">')
                if (i == 0):
                    current = datetime.datetime.now()
                    if (current > lastupdated):
                        self.response.write('Data not parsed for today yet')
                    else:
                        self.response.write('No new kills for this date!')
                else:
                    self.response.write('No new kills for this date!')
                self.response.write('</td>\n')
                self.response.write('</tr>\n')
            else:
                # if there were results, grab the entries for the day and sort
                # them by group name
                updates = r[0].updates
                updates = sorted(updates, key=lambda k: k.group)

                # Grab the global data so we can populate the template with
                # a couple of the values.
                q2 = ctrpmodels.Global.query()
                r2 = q2.fetch()

                # now loop through the groups and output the updates in some
                # fashion.  sort the updates BRF -> HM, then M -> H -> N
                for u in updates:

                    template_values = {
                        'history': u,
                        'num_brf_bosses': ctrpmodels.Constants.num_brf_bosses,
                        'num_hm_bosses': ctrpmodels.Constants.num_hm_bosses,
                    }
                    template = JINJA_ENVIRONMENT.get_template(
                        'templates/history.html')
                    self.response.write(template.render(template_values))

            self.response.write('</tbody>\n')
            curdate -= oneday

        self.response.write('</table>\n')
        template_values = {}
        template = JINJA_ENVIRONMENT.get_template('templates/footer.html')
        self.response.write(template.render(template_values))
