.. kuryr downstream documentation

How to contribute
=================

`Kuryr Midokura downstream repo`_ is an advanced fork of `upstream Kuryr repo`_
to introduce new experimental features before being merged in the community
ones.

We keep a strict policy in terms of repository management workflow in order to
don't get mad between both repositories.

We use `gerrit`_ to do code reviews. Thanks to `.gitreview` file, stored in each
branch we can maintain both projects using different gerrit `remotes`:

  * Upstream repository uses `openstack gerrit`_
  * Downstream repository uses `gerrithub`_

Downstream code will always have upstream + more advanced features, and use a
different branch from **master** for the ongoing development. That means
we can do a clear differentiation between branches and repositories. From each
developer local repository we are able to work with both workflows. This way:

  * For upstream work, we use feature branches cut from **master** branch.
  * Eventually, we may need to backport patches to upstream's **stable**
    branches as well.
  * For downstream work, we use feature branches cut from **k8s** branch.

How to develop
--------------

Setting the `remotes`
^^^^^^^^^^^^^^^^^^^^^

We first need to clone the repositories and set the `remotes`. As we prioritize
the contributions upstream, we'll set the upstream Kuryr repository as `origin`
by cloning from it.

.. code-block:: shell
    :linenos:

    $ git clone http://github.com/openstack/kuryr

After that, we can add the rest of the remotes:

.. code-block:: shell
    :linenos:

    $ git remote add downstream http://github.com/midonet/kuryr
    $ git remote add gerrit ssh://<gerrit-user>@review.openstack.org:29418/opensack/kuryr
    $ git remote add gerrithub ssh://<gerrit-user>@review.gerrithub.io:29418/midonet/kuryr

You now should see something like this when you run `git remote -v`:

.. code-block:: shell
    :linenos:

    $ git remote -v

    downstream https://github.com/midonet/kuryr (fetch)
    downstream https://github.com/midonet/kuryr (push)
    gerrit  ssh://devesa@review.openstack.org:29418/openstack/kuryr.git (fetch)
    gerrit  ssh://devesa@review.openstack.org:29418/openstack/kuryr.git (push)
    gerrithub  ssh://jdevesa@review.gerrithub.io:29418/midonet/kuryr.git (fetch)
    gerrithub  ssh://jdevesa@review.gerrithub.io:29418/midonet/kuryr.git (push)
    origin  http://github.com/openstack/kuryr (fetch)
    origin  http://github.com/openstack/kuryr (push)


Working upstream
^^^^^^^^^^^^^^^^

Working upstream shouldn't be different from what's settled in
`OpenStack Developers Guide`_ , so we won't get into details here.


Working downstream
^^^^^^^^^^^^^^^^^^

We keep basically the same workflow as working upstream except some caveats you
will need to take into account:

- Branches are not cut from **master** but from **k8s**. So **k8s** is the
  ongoing development branch.
- Topic branches must contain the JIRA issue and named as **task/JIRA-ISSUE**
  *without the project name* (Project *IN* is implicit). So **task/67** refers to
  JIRA issue `IN-67`_. Use it regardless if it is a feature or a bug. We don't
  like over-bureaucracy.
- We enforce the use of *Signed-Off-By*, *Closes-Bug* and *Implements* tags.
- Stable branches of downstream not considered yet.
- When pushing reviews to downstream gerrit, use the *-r gerrithub* option.


A whole workflow of downstream patch would be:

.. code-block:: shell
    :linenos:

    $ git checkout k8s
    $ git pull downstream k8s
    $ git checkout -b task/67
    ...  # Do your work
    $ git add <my-changes>
    $ git commit
    $ git review -r gerrithub

A big rule here: **NEVER** **NEVER** submit a patch to review to downstream's
gerrit master branch.

Upstream-Downstream synchronization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Periodically, we need to update the downstream repository with the upstream new
patches. To do so, we need to push directly to *gerrithub* **master** branch. As
we have said, **k8s** branch must **ALWAYS** be on top of **master** branch. So
after pushing **master** branch, we will need to rebase it from **k8s** and
also, push directly as to gerrit **k8s** branch.

.. code-block:: shell
    :linenos:

    # Pull from upstream an
    $ git pull origin master
    $ git push gerrithub master

    # Move to k8s branch and download the last changes
    $ git checkout k8s
    $ git pull downstream k8s

    # Rebase master branch
    $ git rebase master

    # Update downstream k8s branch
    $ git push gerrithub k8s

**NOTE**: Permissions to do this are very restricted. As a regular contributor,
you shouldn't worry about this last step.

Once this is done, some ongoing patches in downstream may need to rebase from
gerrithub site.


.. _`Kuryr Midokura downstream repo`: http://github.com/midonet/kuryr
.. _`upstream Kuryr repo`: http://github.com/openstack/kuryr
.. _`gerrit`: http://www.gerritcodereview.com
.. _`openstack gerrit`: http://review.openstack.org
.. _`gerrithub`: http://review.gerrithub.io
.. _`OpenStack Developers Guide`: http://docs.openstack.org/infra/manual/developers.html
.. _`IN-67`: http://midobugs.atlassian.net/browse/IN-67
