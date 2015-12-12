#!/usr/bin/env python
#
# Copyright (C) 2015 ycmd contributors
#
# This file is part of ycmd.
#
# YouCompleteMe is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# YouCompleteMe is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with YouCompleteMe.  If not, see <http://www.gnu.org/licenses/>.

from ycmd.utils import ToUtf8IfNeeded
from ycmd.completers.completer import Completer
from ycmd import responses, utils

import logging
import urlparse
import requests
import subprocess

import sys
import os

from os import path as p

BINARY_NOT_FOUND_MESSAGE = ( 'racerd binary not found. Did you build it? ' +
                             'You can do so by running ' +
                             '"./install.py --racerd-completer".' )
RUST_SOURCE_NOT_FOUND_MESSAGE = ( 'rust source not found' )
DIR_OF_THIS_SCRIPT = p.dirname( p.abspath( __file__ ) )
DIR_OF_THIRD_PARTY = p.abspath( p.join( DIR_OF_THIS_SCRIPT,
                             '..', '..', '..', 'third_party' ) )
PATH_TO_RACERD = p.join( DIR_OF_THIRD_PARTY, 'racerd', 'target',
                         'release', 'racerd' )

class RustCompleter( Completer ):
  """
  A completer for the rust programming language backed by racerd.
  https://github.com/jwilm/racerd
  """

  def __init__( self, user_options ):
    super( RustCompleter, self ).__init__( user_options )
    self._logger = logging.getLogger( __name__ )
    self._racerd_phandle = None
    self._racerd_binary = self._FindRacerdBinary( user_options )
    self._rust_src_path = self._FindRustSrcPath( user_options )

    if not self._racerd_binary:
      raise RuntimeError( BINARY_NOT_FOUND_MESSAGE )

    if not self._rust_src_path:
      raise RuntimeError( RUST_SOURCE_NOT_FOUND_MESSAGE )


  def SupportedFiletypes( self ):
    return [ 'rust' ]


  def _GetResponse( self, handler, request_data = {} ):
    """
    Query racerd via HTTP

    racerd returns JSON with 200 OK responses. 204 No Content responses occur
    when no errors were encountered but no completions, definitions, or errors
    were found.
    """
    self._logger.info('RustCompleter._GetResponse')
    target = urlparse.urljoin('http://localhost:' + str(self._racerd_port),
                              handler)
    parameters = self._TranslateRequest( request_data )
    response = requests.post( target, json = parameters )
    response.raise_for_status()

    if response.status_code is 204:
      return None

    return response.json()


  def _TranslateRequest( self, request_data ):
    """
    Transform ycm request into racerd request
    """
    if not request_data:
      return {}

    file_path = request_data[ 'filepath' ]
    buffers = []
    for path, obj in request_data[ 'file_data' ].items():
        buffers.append({
            'contents': obj['contents'],
            'file_path': path
        })

    line = request_data[ 'line_num' ]
    col = request_data[ 'column_num' ] - 1

    return {
        'buffers': buffers,
        'line': line,
        'column': col,
        'file_path': file_path
    }


  def _GetExtraData( self, completion ):
      location = {}
      if completion[ 'file_path' ]:
        location[ 'filepath' ] = ToUtf8IfNeeded( completion[ 'file_path' ] )
      if completion[ 'line' ]:
        location[ 'line_num' ] = completion[ 'line' ]
      if completion[ 'column' ]:
        location[ 'column_num' ] = completion[ 'column' ] + 1

      if location:
        extra_data = {}
        extra_data[ 'location' ] = location
        return extra_data
      else:
        return None


  def ComputeCandidatesInner( self, request_data ):
    self._logger.info( 'rust ComputeCandidatesInner' )
    completions = self._FetchCompletions( request_data )
    if completions is None:
      return []

    return [ responses.BuildCompletionData(
                insertion_text = ToUtf8IfNeeded( completion[ 'text' ] ),
                kind = ToUtf8IfNeeded( completion[ 'kind' ] ),
                extra_menu_info = ToUtf8IfNeeded( completion[ 'context' ] ),
                extra_data = self._GetExtraData( completion ) )
             for completion in completions ]


  def _FetchCompletions( self, request_data ):
    return self._GetResponse( '/list_completions', request_data )


  def _FindRacerdBinary( self, user_options ):
    """ Find the path to racerd binary

    If 'racerd_binary_path' in the options is blank,
    use the version installed with YCM, if it exists,
    then the one on the path, if not.

    If the 'racerd_binary_path' is specified, use it
    as an absolute path.

    If the resolved binary exists, return the path,
    otherwise return None. """
    # This is similar to FindGoCodeBinary in gocode_completer
    if user_options.get( 'racerd_binary_path' ):
      if os.path.isfile( user_options[ 'racerd_binary_path' ] ):
        return user_options[ 'racerd_binary_path' ]
      else:
        return None
    if os.path.isfile( PATH_TO_RACERD ):
      return PATH_TO_RACERD
    return utils.PathToFirstExistingExecutable( [ 'racerd' ] )

  def _FindRustSrcPath( self, user_options):
    if user_options.get( 'rust_src_path' ):
      if os.path.isdir( user_options[ 'rust_src_path' ] ):
        return user_options[ 'rust_src_path' ]
      else:
        return None

    src_key = 'RUST_SRC_PATH'
    if os.environ.has_key( src_key ) and os.path.isdir( os.environ[src_key] ):
      return os.environ[src_key]

    return None


  def _StartServer( self ):
    self._racerd_port = utils.GetUnusedLocalhostPort()
    self._racerd_phandle = utils.SafePopen( [
        self._racerd_binary, 'serve', '--port',
                str(self._racerd_port), '--secret-file=not_supported',
                '--rust-src-path', self._rust_src_path
      ], stdout = subprocess.PIPE )

    self._logger.info('racerd serving HTTP on ' + str(self._racerd_port))


  def DefinedSubcommands( self ):
    return [
      'GoTo',
      'GoToDefinition'
      'RestartServer',
      'StopServer',
    ]


  def ServerIsRunning( self ):
    if self._racerd_phandle != None and self._racerd_phandle.poll() == None:
      return True
    return False


  def _StopServer( self ):
    self._racerd_phandle.kill()
    self._racerd_phandle = None


  def RestartServer( self ):
    self._StopServer()
    self._StartServer()


  def _RestartServer( self, request_data ):
    self._RestartServer()


  def OnFileReadyToParse( self, request_data ):
    if not self.ServerIsRunning():
      self._StartServer()


  def OnUserCommand( self, arguments, request_data ):
    if not arguments:
      raise ValueError( self.UserCommandsHelpMessage() )

    command_map = {
      'GoTo' : {
        'method': self._GoToDefinition,
        'args': { 'request_data': request_data }
      },
      'GoToDefinition' : {
        'method': self._GoToDefinition,
        'args': { 'request_data': request_data }
      },
      'GoToDeclaration' : {
        'method': self._GoToDefinition,
        'args': { 'request_data': request_data }
      },
      'StopServer' : {
        'method': self._StopServer,
        'args': { 'request_data': request_data }
      },
      'RestartServer' : {
        'method': self._RestartServer,
        'args': { 'request_data': request_data }
      }
    }

    try:
      command_def = command_map[ arguments[ 0 ] ]
    except KeyError:
      raise ValueError( self.UserCommandsHelpMessage() )

    return command_def[ 'method' ]( **( command_def[ 'args' ] ) )


  def _GoToDefinition( self, request_data ):
    try:
      definition =  self._GetResponse( '/find_definition', request_data )
      return responses.BuildGoToResponse( definition[ 'file_path' ],
                                          definition[ 'line' ],
                                          definition[ 'column' ] + 1 )
    except Exception:
      raise RuntimeError( 'Can\'t jump to definition.' )


  def Shutdown( self ):
    self._StopServer()
