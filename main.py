import webapp2

class MainHandler(webapp2.RequestHandler):
	def get(self):
		self.response.out.write("Do you want to play a game?")

app = webapp2.WSGIApplication([('/', MainHandler)],
	debug=True)
