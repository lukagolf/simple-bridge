# Simple Bridge

## High Level Approach
The bulk of the program is controlled in the main() method, which starts up the bridge and initializes the data structures that I use. For Ports, I have a list consisting of all the ports my bridge has. That list is then passed around to functions that need to send data from them. I chose to take advantage of multithreading by starting a thread that sends BPDUs out on a half-second loop and updates the bridgeInfo as needed. After that, much of the remaining functionality is in the update_bpdu() function, which updates the bridge according to a given BPDU.

I did my best to avoid global variables as they are bad design, but chose to leave the parser args where they were since they are used in several different places. In order to keep my bridge data in a non-global package, I created the class "BridgeInfo". This class contains values such as the port number the bridge uses to communicate with the root, the ID of the bridge currently considered to be the root, the cost of a message going from the bridge to the root, the ID of the bridge that my messages go through to get to the root, and whether the bridge is unconfirmed.

## Good Features
I avoided heavy use of global variables by creating a BridgeInfo class, and I also utilized multi-threading. This allowed me to continue sending out BPDUs while receiving them simultaneously.

## How I Tested
Most of my testing consisted of print debugging and running the simulator incrementally. The print statements were important as they provided insight into the simulator's operations. Based on this, I was able to determine where packets were being dropped or where I wasn't updating the bridge as needed. Once I achieved a satisfactory state where several configs were passing, I primarily relied on the `./test` file to test my code.

## Commands
To run a certain config: `./run configs/simple-1.conf`  
To run all tests: `./test`

