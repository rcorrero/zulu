#!/bin/bash
CONDAENV=$1
CMDFILE=$2
SEEDFILE=$3

# read -p "Conda environment name: " CONDAENV
# read -p "Path to file containing command: " CMDFILE
# read -p "Path to file containing seeds: " SEEDFILE

echo "Conda environment name: $CONDAENV"
echo "Command filepath: $CMDFILE"
echo "Seed filepath: $SEEDFILE"

# read -p "Continue? (Y/N): " confirm && [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]] || exit 1

while read seed; do  
    echo "Seed: $seed"
    while read cmd; do
        echo "Command: $cmd"
        # conda run -n $CONDAENV python -m train $cmd --seed $seed
        # PID=$!
        # wait $PID
    done < $CMDFILE
done < $SEEDFILE