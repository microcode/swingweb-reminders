# coding: utf-8

from xml.dom import minidom
import datetime
import re
import urllib2
import sys
import optparse
import webapp2
import logging
import cgi

from google.appengine.api import mail
from google.appengine.ext import db
from google.appengine.api import users

from email.header import Header

class Configuration(db.Model):
	registrations = db.StringProperty(required=True)
	competitions = db.StringProperty(required=True)
	warningDay = db.IntegerProperty(required=True)
	infoDays = db.IntegerProperty(required=True)
	sender = db.EmailProperty(required=True)
	receiver = db.EmailProperty(required=True)	

class Registration:
	def __init__(self, classType, team, clubs, state):
		self.classType = classType
		self.team = team
		self.clubs = clubs
		self.state = state

class Registrations:
	def __init__(self, url):
		self.results = Registrations.parseRegistrations(url)

	@staticmethod
	def parseRegistrations(url):
		eventRegex = re.compile("event_([0-9]+)")
		nameRegex = re.compile("(.+?)(?:, (.+?))? & (.+)")

		response = urllib2.urlopen(url)
		data = response.read()

		doc = minidom.parseString(data)
		competitions = doc.getElementsByTagName("tbody")[0]

		results = {}

		current = None
		registrations = None

		for row in competitions.getElementsByTagName("tr"):
			if row.hasAttributes() and row.attributes.has_key("id"):
				if (current != None) and (registrations != None):
					results[current] = registrations
				current = int(eventRegex.match(row.attributes["id"].nodeValue).group(1))
				registrations = []
				continue

			if current == None:
				continue

			columns = row.getElementsByTagName("td")
			if len(columns) < 4:
				continue

			team = filter(None, list(nameRegex.match(columns[1].childNodes[0].nodeValue).groups()))
			clubs = map(lambda club: club.childNodes[0].nodeValue, columns[2].getElementsByTagName("span"))

			registration = Registration(
				columns[0].childNodes[0].nodeValue,
				team,
				clubs,
				columns[3].childNodes[0].nodeValue
			)

			registrations.append(registration)

		if (current != None) and (registrations != None):
			results[current] = registrations

		return results

	def has_key(self, id):
		return self.results.has_key(id)

	def __getitem__(self, item):
		return sorted(self.results[item], lambda x,y: cmp(y.classType, x.classType))

class CompetitionType:
	Regional = u'Regional'
	National = u'Nationell'
	Unknown = u'Okänd'

class Competition:
	def __init__(self, organizer, name, direct, late, start, competitionType):
		self.organizer = organizer
		self.name = name
		self.direct = direct
		self.late = late
		self.start = start
		self.competitionType = competitionType

class Competitions:
	def __init__(self, url):
		self.results = Competitions.parseCompetitions(url)

	@staticmethod
	def getDirectDate(schedule):
		try:
			date = schedule.getElementsByTagName("startDirectReg")[0].childNodes[0].nodeValue
		except:
			return Competitions.getLateDate(schedule)

		if date != None:
			date = datetime.datetime.strptime(date, "%Y-%m-%d %H:%M:%S")

		return date

	@staticmethod
	def getLateDate(schedule):
		try:
			date = schedule.getElementsByTagName("startLateReg")[0].childNodes[0].nodeValue
		except:
			try:
				date = schedule.getElementsByTagName("closeReg")[0].childNOdes[0].nodeValue
			except:
				date = None

		if date != None:
			date = datetime.datetime.strptime(date, "%Y-%m-%d %H:%M:%S")

		return date

	@staticmethod
	def getStartDate(schedule):
		try:
			date = schedule.getElementsByTagName("startDate")[0].childNodes[0].nodeValue
			date = datetime.datetime.strptime(date, "%Y-%m-%d")
			return date
		except:
			return None

	@staticmethod
	def parseCompetitions(url):
		response = urllib2.urlopen(url)
		data = response.read()

		doc = minidom.parseString(data)

		results = {}

		for event in doc.getElementsByTagName("event"):
			id = int(event.attributes["eventId"].nodeValue)
			if len(event.getElementsByTagName("registrationPeriods")) == 0:
				continue

			direct = Competitions.getDirectDate(event.getElementsByTagName("registrationPeriods")[0])	
			if direct == None:
				continue

			late = Competitions.getLateDate(event.getElementsByTagName("registrationPeriods")[0])

			start = Competitions.getStartDate(event.getElementsByTagName("schedule")[0])

			name = event.getElementsByTagName("title")[0].childNodes[0].nodeValue	
			organizer = event.getElementsByTagName("organizer")[0].childNodes[0].nodeValue

			if name.endswith("- R"):
				eventType = CompetitionType.Regional
			elif name.endswith("- N"):
				eventType = CompetitionType.National
			else:
				eventType = CompetitionType.Unknown

			results[id] = Competition(
				organizer,
				name,
				direct,
				late,
				start,
				eventType
			)

		return results

	def iteritems(self):
		return sorted(self.results.iteritems(), lambda x,y: cmp(x[1].start, y[1].start));


class MainHandler(webapp2.RequestHandler):
	def get(self):
		query = Configuration.gql("")
		config = query.get()
		if config == None:
			self.response.out.write("NOT_CONFIGURED")
			return

		self.sendMessages(config)
		self.response.out.write('OK')

	def sendMessages(self, config):
		registrations = Registrations(config.registrations)
		competitions = Competitions(config.competitions)

		now = datetime.datetime.now()
		limit = now + datetime.timedelta(days = config.infoDays)

		for id,competition in competitions.iteritems():

			if (config.warningDay != (competition.direct - now).days):
				continue

			template = u'Sista anmälningdag för %s är %s.\nArrangör: %s\nTävlingsstart: %s\n\nAnmäl dig via http://www.swingweb.se/\n\n' % (competition.name, (competition.direct + datetime.timedelta(days = -1)).strftime('%Y-%m-%d'), competition.organizer,competition.start.strftime('%Y-%m-%d'))

			if registrations.has_key(id):
				template += u'Nackswinget har för tillfället %d anmälda par till denna tävling:\n\n' % (len(registrations[id]))

				for reg in registrations[id]:
					template += u' %s - %s - %s (%s)\n' % (reg.classType, ', '.join(reg.team), ' / '.join(reg.clubs), reg.state)
			else:
				template += u'Nackswinget har för tillfället inga par anmälda till denna tävling.\n'

			template += u'\nOm du redan är anmäld till tävlingen så behöver du inte göra det igen.\n'

			template += u'\nInformation om tävlingen: http://www.swingweb.se/public/comp/game/index.php?id=%d\n' % (id)

			template += u'\nTävlingsanmälningar de närmsta %d dagarna:\n\n' % (config.infoDays)
			for nid, ncomp in competitions.iteritems():
				if (config.infoDays < (ncomp.direct - now).days) and ((ncomp.direct - now).days >= 0):
					continue
				template += u' %s - %s (Sista anmälningsdag: %s)\n' % (ncomp.start.strftime('%Y-%m-%d'), ncomp.name, (ncomp.direct + datetime.timedelta(days = -1)).strftime('%Y-%m-%d'))

			subject = competition.name
			#if competition.competitionType != CompetitionType.Unknown:
			#	subject = u'[%s] %s' % (competition.competitionType,subject)

			sender = (u'Tävlingspåminnelse <%s>' % (config.sender)).encode('utf-8')

			message = mail.EmailMessage(sender = sender, to = config.receiver, subject = subject.encode('utf-8'), body = template.encode('utf-8'))
			message.send()

class SetupHandler(webapp2.RequestHandler):
	def get(self):
		query = Configuration.gql("")
		config = query.get()
		if config == None:
			config = Configuration(registrations = "http://", competitions = "http://", warningDay = -1, infoDays = -1, sender = "user@example.com", receiver = "user@example.com")

		self.response.out.write("""
<html>
	<body>
		<form method="post">
			<div><span>Registrations</span><span><input type="text" name="registrations" value="%s"></span></div>
			<div><span>Competitions</span><span><input type="text" name="competitions" value="%s"></span></div>
			<div><span>Warning Day</span><span><input type="text" name="warningDay" value="%d"></span></div>
			<div><span>Info Days</span><span><input type="text" name="infoDays" value="%d"></span></div>
			<div><span>Sender</span><span><input type="text" name="sender" value="%s"></span></div>
			<div><span>Receiver</span><span><input type="text" name="receiver" value="%s"></span></div>
			<div><button>Save</button></div>
		</form>
	</body>
</html>
		""" % (config.registrations, config.competitions, config.warningDay, config.infoDays, config.sender, config.receiver))

	def post(self):
		query = Configuration.gql("")
		config = query.get()

		logging.info(self.request.get("competitions"))

		if config == None:
			config = Configuration(registrations = cgi.escape(self.request.get("registrations")), competitions = cgi.escape(self.request.get("competitions")), warningDay = int(cgi.escape(self.request.get("warningDay"))), infoDays = int(cgi.escape(self.request.get("infoDays"))), sender = cgi.escape(self.request.get("sender")), receiver = cgi.escape(self.request.get("receiver")))
		else:
			config.registrations = cgi.escape(self.request.get("registrations"))
			config.competitions = cgi.escape(self.request.get("competitions"))
			config.warningDay = int(cgi.escape(self.request.get("warningDay")))
			config.infoDays = int(cgi.escape(self.request.get("infoDays")))
			config.sender = cgi.escape(self.request.get("sender"))
			config.receiver = cgi.escape(self.request.get("receiver")) 

		config.put()

		self.response.out.write("SAVED")

app = webapp2.WSGIApplication([('/mail/reminders', MainHandler), ('/setup', SetupHandler)],
			debug=True)


