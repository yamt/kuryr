..
    This work is licensed under a Creative Commons Attribution 3.0 Unported
    License.

    http://creativecommons.org/licenses/by/3.0/legalcode

    Convention for heading levels in Neutron devref:
    =======  Heading 0 (reserved for the title in a document)
    -------  Heading 1
    ~~~~~~~  Heading 2
    +++++++  Heading 3
    '''''''  Heading 4
    (Avoid deeper levels because they do not render well.)

=============
Kuryr Testing
=============

This document describes the guidelines for Kuryr testing and gives some tips
and tricks for an easier development experience.

Guidelines
----------

There are a few rules that every patch to Kuryr should obey in general,
although exceptions can be made when sufficient core contributor consensus on
the issue is achieved

* Every bug fix should incorporate a test case that prevents a future
  regression.
* Code additions should have unit test coverage.

Getting started
---------------

In order to test Kuryr you should make sure that you have the right
dependencies for running tox and the Kuryr test requirements.

Dependencies
~~~~~~~~~~~~
Ubuntu
++++++

::

    sudo apt-get install git python-dev python3-dev python-gdbm python3-gdbm
    sudo pip install tox

Arch Linux
++++++++++

::

    yaourt -S git python2-pip python-pip python34
    sudo pip install tox


Running the tests
~~~~~~~~~~~~~~~~~

One can run the pep8 tests by doing:

::

    tox -e pep8

To run the python3.4 tests:

::

    tox -e py34

To run the python2.7 tests:

::

    tox -e py27

Tips
----

Running specific modules
~~~~~~~~~~~~~~~~~~~~~~~~

To run specific test modules, you can do:

::

    tox -e py34 -v kuryr.tests.unit.test_raven

Where the -v provides more verbose tox output. Note that you could also use
regex to specify a single test:

::

    tox -e py34 -v -- '(test_k8s_api_watcher|test_watch_cb_1_coroutine)'

Listing available tests
~~~~~~~~~~~~~~~~~~~~~~~

::

    source .tox/py34/bin/activate
    testr list-tests

Running tests from a file list
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can put a test per line in a file and run all the tests in it. For the
right test names, see the testr list-tests command

::

    source .tox/py34/bin/activate
    python -m testtools.run discover --load-list tests_to_run


Avoiding requirements checks on repeated tests and getting better output
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    source .tox/py34/bin/activate
    python -m testtools.run kuryr.tests.unit.test_raven

Asyncio debug mode
~~~~~~~~~~~~~~~~~~

::

    source .tox/py34/bin/activate
    PYTHONASYNCIODEBUG=1 python -m testtools.run kuryr.tests.unit.test_raven
