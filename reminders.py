# coding: utf-8

from xml.dom import minidom
import datetime
import re
import urllib2
import sys
import optparse
import webapp2
import logging

from google.appengine.api import mail

registrationUrl = "http://www.swingweb.org/tools/comp/registrations/?org=NSW&format=htmlBody;encoding=UTF-8"
#registrationUrl = "http://www.swingweb.org/tools/comp/registrations/?format=htmlBody;encoding=UTF-8"
competitionsUrl = "https://swingweb.se/xml/?type=games&maxRows=1000"

warningDays = 5
infoDays = 30

mailServer = "localhost"
mailSender = "tavlingspaminnelse@nackswinget.se"
mailReceiver = "tavlingspaminnelse-nackswinget@googlegroups.com"

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
		logging.info("Requesting items for %d: " % item)
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
		self.sendMessages()
		self.response.out.write('Processing complete!')

	def sendMessages(self):
		registrations = Registrations(registrationUrl)
		competitions = Competitions(competitionsUrl)

		now = datetime.datetime.now()
		limit = now + datetime.timedelta(days = infoDays)

		for id,competition in competitions.iteritems():

			if (warningDays != (competition.direct - now).days):
				#continue
				pass

			template = u'Sista anmälningdag för %s är %s.\nArrangör: %s\nTävlingsstart: %s\n\nAnmäl dig via http://www.swingweb.se/\n\n' % (competition.name, (competition.direct + datetime.timedelta(days = -1)).strftime('%Y-%m-%d'), competition.organizer,competition.start.strftime('%Y-%m-%d'))

			if registrations.has_key(id):
				template += u'Nackswinget har för tillfället %d anmälda par till denna tävling:\n\n' % (len(registrations[id]))

				for reg in registrations[id]:
					template += u' %s - %s - %s (%s)\n' % (reg.classType, ', '.join(reg.team), ' / '.join(reg.clubs), reg.state)
			else:
				template += u'Nackswinget har för tillfället inga par anmälda till denna tävling.\n'

			template += u'\nOm du redan är anmäld till tävlingen så behöver du inte göra det igen.\n'

			template += u'\nInformation om tävlingen: http://www.swingweb.se/public/comp/game/index.php?id=%d\n' % (id)

			template += u'\nTävlingsanmälningar de närmsta %d dagarna:\n\n' % (infoDays)
			for nid, ncomp in competitions.iteritems():
				if (infoDays < (ncomp.direct - now).days) and ((ncomp.direct - now).days >= 0):
					continue
				template += u' %s - %s (Sista anmälningsdag: %s)\n' % (ncomp.start.strftime('%Y-%m-%d'), ncomp.name, (ncomp.direct + datetime.timedelta(days = -1)).strftime('%Y-%m-%d'))

			subject = competition.name
			#if competition.competitionType != CompetitionType.Unknown:
			#	subject = u'[%s] %s' % (competition.competitionType,subject)

			message = mail.EmailMessage(sender = u'Tävlingspåminnelse <%s>'.encode('utf-8') % mailSender, to = mailReceiver, subject = subject.encode('utf-8'), body = template.encode('utf-8'))
			message.send()

			break

app = webapp2.WSGIApplication([('/mail/reminders', MainHandler)],
			debug=True)


