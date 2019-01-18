#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import webapp2
import ctrpmodels
import display
import ranker
import rostermgmt

app = webapp2.WSGIApplication([
    (r'/', display.Display),
    (r'/history', display.DisplayHistory),
    (r'/loadgroups', rostermgmt.RosterBuilder),
    (r'/rank', ranker.Ranker),
    (r'/builder', ranker.ProgressBuilder),
    (r'/migrate', ctrpmodels.MigrateT22toT23),
    (r'/tier(\d+)', display.DisplayTier),
    webapp2.Route(r'/fixgroupnames', rostermgmt.RosterBuilder, handler_method='fix_groupnames'),
    webapp2.Route(r'/tooltips.js', display.Display, handler_method='build_tooltips'),
    webapp2.Route(r'/loadone', ranker.ProgressBuilder, handler_method='loadone'),
    webapp2.Route(r'/startrank', ranker.Ranker, handler_method='post'),
], debug=True)
