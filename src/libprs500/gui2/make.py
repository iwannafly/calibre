##    Copyright (C) 2007 Kovid Goyal kovid@kovidgoyal.net
##    This program is free software; you can redistribute it and/or modify
##    it under the terms of the GNU General Public License as published by
##    the Free Software Foundation; either version 2 of the License, or
##    (at your option) any later version.
##
##    This program is distributed in the hope that it will be useful,
##    but WITHOUT ANY WARRANTY; without even the implied warranty of
##    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##    GNU General Public License for more details.
##
##    You should have received a copy of the GNU General Public License along
##    with this program; if not, write to the Free Software Foundation, Inc.,
##    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
'''
Manage the PyQt build system pyrcc4, pylupdate4, lrelease and friends.
'''

import sys, os, subprocess, cStringIO, compiler
from functools import partial

from PyQt4.uic import compileUi

check_call = partial(subprocess.check_call, shell=True)

def find_forms():
    forms = []
    for root, dirs, files in os.walk('.'):
        for name in files:
            if name.endswith('.ui'):
                forms.append(os.path.abspath(os.path.join(root, name)))
        
    return forms

def form_to_compiled_form(form):
    return form.rpartition('.')[0]+'_ui.py'

def build_forms(forms):
    for form in forms:
        compiled_form = form_to_compiled_form(form) 
        if not os.path.exists(compiled_form) or os.stat(form).st_mtime > os.stat(compiled_form).st_mtime:
            print 'Compiling form', form
            buf = cStringIO.StringIO()
            compileUi(form, buf)
            dat = buf.getvalue()
            dat = dat.replace('import images_rc', 'from libprs500.gui2 import images_rc')
            dat = dat.replace('from library import', 'from libprs500.gui2.library import')
            open(compiled_form, 'wb').write(dat)
                
def build_images():
    newest = 0
    for root, dirs, files in os.walk('./images'):
        for name in files:
            newest = max(os.stat(os.path.join(root, name)).st_mtime, newest)
    
    newest = max(newest, os.stat('images.qrc').st_mtime)
    
    if not os.path.exists('images_rc.py') or newest > os.stat('images_rc.py').st_mtime:
        print 'Compiling images'
        check_call(' '.join(['pyrcc4', '-o', 'images_rc.py', 'images.qrc']))
        compiler.compileFile('images_rc.py')
        os.utime('images_rc.py', None)
        os.utime('images_rc.pyc', None)
            

def build(forms):
    build_forms(forms)
    build_images()

def clean(forms):
    for form in forms:
        compiled_form = form_to_compiled_form(form)
        if os.path.exists(compiled_form):
            print 'Removing compiled form', compiled_form
            os.unlink(compiled_form)
    print 'Removing compiled images'
    os.unlink('images_rc.py')
    os.unlink('images_rc.pyc')

def main(args=sys.argv):
    
    if not os.getcwd().endswith('gui2'):
        raise Exception('Must be run from the gui2 directory')
    
    forms = find_forms()
    if len(args) == 1:
        args.append('all')
    
    if args[1] == 'all':
        build(forms)
    elif args[1] == 'clean':
        clean(forms)
    elif args[1] == 'test':
        build(forms)
        print 'Running main.py'
        subprocess.call('python main.py', shell=True)
    else:
        print 'Usage: %s [clean|test|all]'%(args[0])
        return 1 
    
    return 0

if __name__ == '__main__':
    sys.exit(main())