# Writes a goodbye message to the user

characters = ["g", "o", "d", "b", "y", "e"]

for c in characters:
    if c != "o":
        print(c,end="")
    else:
        print(c,c, sep="",end="")

print("")