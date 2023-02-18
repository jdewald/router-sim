# routersim

## What the heck is this?

This repository contains a toy implementation of router technologies intended for exploration and learning. 
Specifically, it will implement various routing protocols (IS-IS, OSPF, BGP, static) as well as performing routing (forwarding) of packets based on the derived tables.

In terms of router implementation the following is there:
* Packet forwarding
* Distinct route tables (that feed forwarding tables)
* IS-IS routing protocol for learning routes
* RSVP-TE with Facility protection 
* Forwarding via MPLS of "BGP-learned" routes
* PING/ICMP 

A work-in-progress branch has added:
* Layer 2 support
* Switching
* ARP

Additionally there is WIP for:
* RSTP (sort of a requirement to do Layer2 with arbitrary topologies)

The tooling around it can generate:
* Sequence diagrams
* Topology diagrams

The key aspect of the functionality is that it operates in discrete time units and generates events which can be used to create various interaction diagrams (Sequence, Activity, Timing, etc). 

Additionally, to aid in the exploration there are convenience classes and methods for quickly spinning up a topology.

At the time of this writing, there are no external dependencies on the Python side (it is written for Python3). To view the generated PlantUML diagrams it is helpful to have a `plantuml` binary in the path, but they can also be viewed in VSCode.

## Jupyter notebook

As a mechanism to provide an all-in-one and convenient method to run and view the simulation, this repository also contains a `Dockerfile` which will generate a container image which has Jupyter notebook, the routersim, and various binaries (such as `plantuml`). 

You can see an example of what the [notebook can do here](samples/demos/001_lan.ipynb).
### QuickStart

This QuickStart assumes you have access to Docker

After cloning:

`docker build -f Dockerfile -t routersim:latest .`

Then to start it up and use the pre-built 'demos' directory without needing to re-upload:

`docker run -v $PWD/demos:/home/jovyan/work -p 8888:8888 routersim:latest`

You can also copy notebooks over wherever you might want and just mount that directory. 
NOTE: that `/home/joyvan/work` should be left as-is, as it's from the base notebook and I didn't see a reason to change.

After it starts, it will give a token-based link which you can open in your browser.

Eventually I'll push up a docker image you can use without needing to build. 

## Simple Networking Tutorials

I am (slowly) building up a catalog of something akin to networking tutorials using the simulator, those
can be found in the `demos` directory prefixed with a 3-digit number, which would be the suggested order
to view and interact with them. If you are looking at this in GitHub, or have the code loaded into VSCode
you should be able to click/load those without actually needing to run if you want to see the output.

The `samples` directory contains non-interactive output of the Jupyter notebook which you can definitely 
load without using Jupyter or Python or anything else.


## Internals

### Events


