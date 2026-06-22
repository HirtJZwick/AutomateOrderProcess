
def main():
    # Write the output to a file
    with open("output.txt", "w") as file:
        file.write("Script invoked\n")
    print("Script invoked")


if __name__ == "__main__":
    main()
