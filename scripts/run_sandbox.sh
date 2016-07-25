#!/bin/bash
SANDBOX_VERSION=${SANDBOX_VERSION:-dev}
SANDBOX_PULL=${SANDBOX_PULL:-true}

if [[ "$1" == "start" ]]; then

    echo "-------------- Running the sandbox for Raven development..."
    echo ""
    echo ""
    echo ""
    kuryr_path=$(dirname $(dirname $(realpath $0)))
    if [ ! -L /tmp/kuryr_dev ]; then
        echo "Creating a simlink from ".$kuryr_path." to /tmp/kuryr_dev..."
        ln -s $kuryr_path /tmp/kuryr_dev
    fi

    # TODO(devvesa): uncomment these lines once artifactory is ready
    # Pulling all the images
    # echo "Pulling all the needed images"
    if [[ ${SANDBOX_PULL} == "true" ]]; then
        sandbox-manage -c /tmp/kuryr_dev/sandbox/sandbox_kuryr.cfg pull-all k8s+5+liberty
        sandbox-manage -c /tmp/kuryr_dev/sandbox/sandbox_kuryr.cfg pull-all $SANDBOX_VERSION
    else
        # Build the images
        sandbox-manage -c /tmp/kuryr_dev/sandbox/sandbox_kuryr.cfg build-all k8s+5+liberty
        sandbox-manage -c /tmp/kuryr_dev/sandbox/sandbox_kuryr.cfg build-all $SANDBOX_VERSION
    fi

    echo "Running the development version"
    sandbox-manage -c /tmp/kuryr_dev/sandbox/sandbox_kuryr.cfg run --name=k8s --provision=/tmp/kuryr_dev/sandbox/keystone-provisioning.sh $SANDBOX_VERSION

    if [[ "$SANDBOX_VERSION" == "dev" ]]; then
        docker run -d --net=host --pid=host --privileged -e "K8S_API=http://172.17.0.1:8080" --name=mnsandboxk8s_kubelet_1 -v $kuryr_path/kuryr:/usr/local/lib/python3.4/dist-packages/kuryr -v $kuryr_path/usr:/usr/local/lib/python3.4/dist-packages/usr -v /etc/midolman -v /:/rootfs:ro -v /sys:/sys:ro -v /var/lib/docker:/var/lib/docker:rw -v /var/lib/kubelet:/var/lib/kubelet:rw -v /var/run:/var/run:rw --volumes-from mnsandboxk8s_zookeeper1_1 --volumes-from mnsandboxk8s_midolman_1 sandbox/kubernetes:1.2.0 /run_kubernetes.sh
    fi

    echo ""
    echo ""
    echo ""
    echo "-------------- DONE"

else

  if [[ "$1" == "stop" ]]; then
      echo "-------------- Stopping the sandbox...."
      echo ""
      echo ""
      echo ""
      sandbox-manage -c /tmp/kuryr_dev/sandbox/sandbox_kuryr.cfg kill-all
      docker stop $(docker ps -q)
      docker stop $(docker ps -q)
      echo ""
      echo ""
      echo ""
      echo "-------------- DONE"
  else
      echo "Usage: ./run_sandbox.sh [start|stop]"
  fi

fi
