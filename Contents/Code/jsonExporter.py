######################################################################################################################
#	json Exporter module for WebTools
#
#	Author: dane22, a Plex Community member
#
######################################################################################################################

import os, io
from consts import DEBUGMODE, JSONTIMESTAMP
import datetime
import json
from shutil import move

FILEEXT = '.json'

statusMsg = 'idle'																																									# Response to getStatus
runningState = 0																																										# Internal tracker of where we are
bAbort = False																																											# Flag to set if user wants to cancel

class jsonExporter(object):
	init_already = False							# Make sure init only run once
	bResultPresent = False						# Do we have a result to present

	# Defaults used by the rest of the class
	def __init__(self):
		self.MediaChuncks = 40
		self.CoreUrl = 'http://127.0.0.1:32400/library/sections/'
		# Only init once during the lifetime of this
		if not jsonExporter.init_already:
			jsonExporter.init_already = True
			self.populatePrefs()
			Log.Debug('******* Starting jsonExporter *******')

	''' Populate the defaults, if not already there '''
	def populatePrefs(self):
		if Dict['jsonExportTimeStamps'] == None:
			Dict['jsonExportTimeStamps'] = {}
			Dict.Save()

	''' Grap the tornado req, and process it for a POST request'''
	def reqprocessPost(self, req):
		function = req.get_argument('function', 'missing')
		if function == 'missing':
			req.clear()
			req.set_status(412)
			req.finish("<html><body>Missing function parameter</body></html>")
		elif function == 'export':
			return self.export(req)
		else:
			req.clear()
			req.set_status(412)
			req.finish("<html><body>Unknown function call</body></html>")

	def export(self, req):
		''' Return the type of the section '''
		def getSectionType(section):
			url = 'http://127.0.0.1:32400/library/sections/' + section + '/all?X-Plex-Container-Start=1&X-Plex-Container-Size=0'
			try:
				return XML.ElementFromURL(url).xpath('//MediaContainer/@viewGroup')[0]
			except:
				return "None"

		''' Create a simple entry in the videoDetails tree '''
		def makeSimpleEntry(media, videoDetails, el):
			try:
				entry = unicode(videoDetails.get(el))
				if entry != 'None':
					media[el] = entry
			except:
				pass

		''' Create an array based entry, based on the tag attribute '''
		def makeArrayEntry(media, videoDetails, el):
			try:
				Entries = videoDetails.xpath('//' + el)
				EntryList = []
				for Entry in Entries:
					try:
						EntryList.append(unicode(Entry.xpath('@tag')[0]))
					except:
						pass
				media[el] = EntryList
			except:
				pass
		
		''' Export the actual .json file, as well as poster and fanart '''
		def makeFiles(ratingKey):
			videoDetails = XML.ElementFromURL('http://127.0.0.1:32400/library/metadata/' + ratingKey).xpath('//Video')[0]
			try:
				media = {}
				''' Now digest the media, and add to the XML '''
				# Id
#				try:
#					media['guid'] = videoDetails.get('guid')
#				except:
#					pass
				media['About This File'] = 'JSON Export Made with WebTools for Plex'
				# Simple entries
				elements = ['guid', 'title', 'originalTitle', 'titleSort', 'type', 'summary', 'duration', 'rating', 'ratingImage', 'contentRating', 'studio', 'year', 'tagline', 'originallyAvailableAt', 'audienceRatingImage', 'audienceRating']
				for element in elements:
					makeSimpleEntry(media, videoDetails, element)
				arrayElements = ['Genre', 'Collection', 'Director', 'Writer', 'Producer', 'Country', 'Label']
				for element in arrayElements:
					makeArrayEntry(media, videoDetails, element)
				# Locked fields
				Locked = []
				try:
					Fields = videoDetails.xpath('//Field')
					for Field in Fields:
						try:
							if Field.xpath('@locked')[0] == '1':
								Locked.append(unicode(Field.xpath('@name')[0]))
						except:
							pass
					media['Field'] = Locked
				except:
					pass
				# Role aka actor
				try:
					Roles = videoDetails.xpath('//Role')
					orderNo = 1
					Actors = []					
					for Role in Roles:
						Actor = {}
						try:
							Actor['name'] = unicode(Role.xpath('@tag')[0])
						except:
							pass
						try:
							Actor['role'] = unicode(Role.xpath('@role')[0])
						except:
							pass
						try:
							Actor['order'] = orderNo
							orderNo += 1
						except:
							pass
						try:
							Actor['thumb'] = Role.xpath('@thumb')[0]
						except:
							pass
						Actors.append(Actor)
					media['Role'] = Actors
				except Exception, e:
					Log.Exception('Ged Exception', str(e))
					pass									
				# Let's start by grapping relevant files for this movie
				fileNames = videoDetails.xpath('//Part')
				for fileName in fileNames:
					filename = fileName.xpath('@file')[0]
					filename = String.Unquote(filename).encode('utf8', 'ignore')
					# Get name of json file
					plexJSON = os.path.splitext(filename)[0] + FILEEXT
					Log.Debug('Name and path to plexJSON file is: ' + plexJSON)
					try:
						with io.open(plexJSON, 'w', encoding='utf-8') as outfile:
							outfile.write(unicode(json.dumps(media, indent=4, sort_keys=True)))
					except Exception, e:
						Log.Debug('Exception happend during saving %s. Exception was: %s' %(plexJSON, str(e)))
					# Make poster
					posterUrl = 'http://127.0.0.1:32400' + videoDetails.get('thumb')
					targetFile = os.path.splitext(filename)[0] + '-poster.jpg'
					response = HTTP.Request(posterUrl)
					with io.open( targetFile, 'wb' ) as fo:
						fo.write( response.content )
						Log.Debug('Poster saved as %s' %targetFile)
					# Make fanart
					posterUrl = 'http://127.0.0.1:32400' + videoDetails.get('art')
					targetFile = os.path.splitext(filename)[0] + '-fanart.jpg'
					response = HTTP.Request(posterUrl)
					with io.open( targetFile, 'wb' ) as fo:
						fo.write( response.content )
						Log.Debug('FanArt saved as %s' %targetFile)
			except Exception, e:
				Log.Exception('Exception happend in generating json file: ' + str(e))
			
		''' Scan a movie section '''
		def scanMovieSection(req, sectionNumber):
			Log.Debug('Starting scanMovieSection')		
			global AmountOfMediasInDatabase
			global mediasFromDB
			global statusMsg
			global runningState
			try:		
				# Start by getting the last timestamp for a scanning:
				if sectionNumber in Dict['jsonExportTimeStamps'].keys():					
					timeStamp = Dict['jsonExportTimeStamps'][sectionNumber]
				else:
					# Setting key for section to epoch start
					Dict['jsonExportTimeStamps'][sectionNumber] = 0
					Dict.Save()
					timeStamp = 0
				# Debug mode?
				if JSONTIMESTAMP != 0:
					timeStamp = JSONTIMESTAMP
				now = int((datetime.datetime.now()-datetime.datetime(1970,1,1)).total_seconds())	
				Log.Debug('Starting scanMovieDb for section %s' %(sectionNumber))
				Log.Debug('Only grap medias updated since: ' + datetime.datetime.fromtimestamp(int(timeStamp)).strftime('%Y-%m-%d %H:%M:%S'))
				runningState = -1
				statusMsg = 'Starting to scan database for section %s' %(sectionNumber)
				# Start by getting the totals of this section			
				totalSize = XML.ElementFromURL(self.CoreUrl + sectionNumber + '/all?updatedAt>=' + str(timeStamp) + '&X-Plex-Container-Start=1&X-Plex-Container-Size=0').get('totalSize')
				AmountOfMediasInDatabase = totalSize
				Log.Debug('Total size of medias are %s' %(totalSize))
				if totalSize == '0':					
					# Stamp dict with new timestamp
					Dict['jsonExportTimeStamps'][sectionNumber] = now
					Dict.Save()
					Log.Debug('Nothing to process...Exiting')
					return
				iStart = 0
				iCount = 0
				statusMsg = 'Scanning database item %s of %s : Working' %(iCount, totalSize)
				# So let's walk the library
				while True:
					# Grap a chunk from the server
					videos = XML.ElementFromURL(self.CoreUrl + sectionNumber + '/all?updatedAt>=' + str(timeStamp) + '&X-Plex-Container-Start=' + str(iStart) + '&X-Plex-Container-Size=' + str(self.MediaChuncks)).xpath('//Video')
					# Walk the chunk
					for video in videos:
						if bAbort:
							raise ValueError('Aborted')
						iCount += 1
						makeFiles(video.get('ratingKey'))		
						statusMsg = 'Scanning database: item %s of %s : Working' %(iCount, totalSize)
					iStart += self.MediaChuncks
					if len(videos) == 0:
						statusMsg = 'Scanning database: %s : Done' %(totalSize)
						Log.Debug('***** Done scanning the database *****')
						runningState = 1
						break
				# Stamp dict with new timestamp
				Dict['jsonExportTimeStamps'][sectionNumber] = now
				Dict.Save()
				return
			except Exception, e:
				Log.Exception('Fatal error in scanMovieDb: ' + str(e))
				runningState = 99
		# End scanMovieDb


		def scanShowSection(req, sectionNumber):
			print 'Ged1 scanShowSection'	


		# ********** Main function **************
		Log.Debug('json export called')
		try:
			section = req.get_argument('section', '_export_missing_')
			if section == '_export_missing_':
				req.clear()
				req.set_status(412)
				req.finish("<html><body>Missing section parameter</body></html>")
			if getSectionType(section) == 'movie':
				scanMovieSection(req, section)
			elif getSectionType(section) == 'show':
				scanShowSection(req, section)
			else:
				Log.Debug('Unknown section type for section:' + section + ' type: ' + getSectionType(section))
				req.clear()
				req.set_status(404)
				req.finish("Unknown sectiontype or sectiion")
		except Exception, e:
			Log.Exception('Exception in json export' + str(e))







