import ast
import os
from pydriller import Repository
from pydriller.domain.commit import ModificationType
import re
from datetime import datetime
from git import Repo

def list_branches(repo):
    # Get a list of all branches
    all_branches = [b.name for b in repo.branches]

    # Get a list of branches merged into master
    merged_branches = repo.git.branch('--merged').split("\n")
    merged_branches = [b.strip() for b in merged_branches]

    # Get a list of branches not merged into master
    unmerged_branches = list(set(all_branches) - set(merged_branches))

    # Exclude the current branch (main) from the unmerged branches list
    current_branch = repo.active_branch.name
    if current_branch in unmerged_branches:
        unmerged_branches.remove(current_branch)

    # Write the branches to a file
    with open(os.path.join("results", 'branches.txt'), 'w') as f:
        f.write("Merged branches:\n")
        for branch in merged_branches:
            f.write(branch + "\n")

        f.write("\nUnmerged branches:\n")
        for branch in unmerged_branches:
            f.write(branch + "\n")

    return merged_branches, unmerged_branches

def get_package_versions(filename):
    package_versions = {}
    with open(filename) as f:
        for line in f:
            match = re.match(r"(\w+)==([\d.]+)", line)
            if match:
                package_name, version = match.groups()
                package_versions[package_name] = version
    return package_versions

def get_commit_history(repo, branches):
    # Initialize an empty list to store the commit history
    commit_history = []

    # Iterate over the branches
    for branch in branches:
        # remove the '*' character and strip leading and trailing white spaces
        branch = branch.replace('*', '').strip()
        # Iterate over the commits in the current branch
        for commit in repo.iter_commits(branch):
            try:
                # Extract the commit date and format it as a string
                commit_date = datetime.fromtimestamp(commit.committed_date).strftime('%Y-%m-%d %H:%M:%S')
                # Extract the files changed in the commit
                changed_files = commit.stats.files

                # Create a dictionary to store information about the commit
                commit_info = {
                    'sha': commit.hexsha,
                    'author': commit.author.name,
                    'date': commit_date,
                    'message': commit.message.strip(),
                    'files': changed_files
                }

                # Append the commit information to the commit history list
                commit_history.append(commit_info)

            except ValueError as e:
                # Print the error message for debugging purposes
                print(f"Error encountered while processing commit {commit.hexsha}: {str(e)}")

    # Return the commit history list
    return commit_history

def write_commit_history_to_file(commit_history, file_path):
    """
    Writes the commit history to a file.

    Parameters:
    commit_history (list): A list of dictionaries, where each dictionary contains information about a commit.
    file_path (str): The path to the file where the commit history should be written.

    Returns:
    None
    """
    # Open the file in write mode
    with open(file_path, 'w') as f:
        # Iterate over the commit history
        for commit in commit_history:
            # Write the commit information to the file
            f.write(f"SHA: {commit['sha']}\n")
            f.write(f"Author: {commit['author']}\n")
            f.write(f"Date: {commit['date']}\n")
            f.write(f"Message: {commit['message']}\n")
            f.write("Files:\n")
            for file_name, stats in commit['files'].items():
                f.write(f"  {file_name}: {stats}\n")
            f.write("\n")  # Add a blank line for readability

def extract_dependency_version(file_path):
    package_versions = {}

    with open(file_path) as f:
        for line in f.readlines():
            match = re.match(r'([a-zA-Z0-9-_]+)([=><!~]+)(\d(?:\d|\.|\w|\*|)*)', line)
            if match:
                package_name, _, version = match.groups()
                package_versions[package_name] = version

    return package_versions

def extract_imports(source_code):
    try:
        # Parse the source code to create an Abstract Syntax Tree (AST)
        tree = ast.parse(source_code)

        # Find all import and import-from nodes in the AST
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]

        # Extract the names of the imported modules from the import nodes
        imported_modules = []
        for import_node in imports:
            if isinstance(import_node, ast.Import):
                for alias in import_node.names:
                    imported_modules.append(alias.name)
            elif isinstance(import_node, ast.ImportFrom):
                module = import_node.module
                for alias in import_node.names:
                    imported_modules.append(f"{module}.{alias.name}")

        return imported_modules

    except SyntaxError:
        # Return None if there is a syntax error in the source code
        return None

def extract_dependencies(repo_url, local_directory, from_commit=None, to_commit=None, filepath_filter=None):   
    dependencies = {}  # A dictionary to store the dependencies for each file
    ignored_files = 0  # Counter for files with syntax issues
    other_extensions = []  # List to store file names with different extensions

    # Create the Repository instance using either repo_url or local_directory
    if repo_url is not None:
        repo = Repository(repo_url, from_commit=from_commit, to_commit=to_commit)
    elif local_directory is not None:
        repo = Repository(local_directory, from_commit=from_commit, to_commit=to_commit)
    else:
        raise ValueError("Either repo_url or local_directory must be provided.")

    # Traverse through the commits in the repository
    for commit in repo.traverse_commits():
        try:
            # Iterate through the modified files in each commit
            for mod in commit.modified_files:
                # Check if the file has a .py extension
                if mod.filename.endswith('.py'):
                    # Process only ADD and MODIFY file changes
                    if mod.change_type == ModificationType.ADD or mod.change_type == ModificationType.MODIFY:
                        try:
                            # Extract dependencies from the source code
                            file_dependencies = extract_imports(mod.source_code)

                            # If there are no syntax issues, update the dependencies dictionary
                            if file_dependencies is not None:
                                file_name = mod.filename
                                if file_name in dependencies:
                                    dependencies[file_name] = list(set(dependencies[file_name]) | set(file_dependencies))
                                else:
                                    dependencies[file_name] = file_dependencies
                            else:
                                # Increment the counter for ignored files with syntax issues
                                ignored_files += 1
                        except Exception as e:
                            print(f"Error analyzing {mod.filename}: {e}")
                else:
                    # Add the file to the list of files with different extensions
                    other_extensions.append(mod.filename)
        except ValueError as ve:
            print(f"ValueError encountered while processing commit {commit.hash}: {ve}")
            continue

    # Return the dependencies dictionary, ignored files count, and the list of files with different extensions
    return dependencies, ignored_files, other_extensions

# Check if the script is being run as the main module
if __name__ == "__main__":
    # URL of the Git repository to analyze
    repo_url = None

    local_directory="/home/devops/projects/github_repos/flask"

    if not os.path.exists(local_directory):
        print("The local directory does not exist")
        exit(1)

    # Create a Repo object
    repo = Repo(local_directory)

    # Create the results directory if it doesn't exist
    os.makedirs("results", exist_ok=True)

    # Get merged and unmerged branches
    merged_branches, unmerged_branches = list_branches(repo)

    # Get the list of merged branches from the 'list_branches' function
    merged_branches, unmerged_branches = list_branches(repo)

    # Get the commit history for the merged branches
    commit_history = get_commit_history(repo, merged_branches)

    # assuming merged_branches is a list of names of the merged branches
    for branch_name in merged_branches:
        branches = [branch_name]
        commit_history = get_commit_history(repo, branches)
        # Write the commit history to the file
        commit_history_file_path = os.path.join("results", f"{branch_name}_commit_history.txt")
        write_commit_history_to_file(commit_history, commit_history_file_path)

    # Extract dependencies, count of ignored files, and list of files with different extensions
    dependencies, ignored_files, other_extensions = extract_dependencies(repo_url, local_directory)

    # Get package versions from the requirements.txt file
    package_versions = get_package_versions("requirements.txt")

    # Update the for loop that prints dependencies
with open('results/dependencies.txt', 'w') as dep_file:
    # Update the for loop that prints dependencies
    for file_name, file_dependencies in dependencies.items():
        # Print the file name
        print(f"File: {file_name}", file=dep_file)

        # Print the list of dependencies for the file
        print("Dependencies:", file=dep_file)
        for dependency in file_dependencies:
            # Get the version from the package_versions dictionary
            version = package_versions.get(dependency.split('.')[0], "unknown")
            print(f"  {dependency} = {version}", file=dep_file)
        print(file=dep_file)  # Add a newline for readability


    # Save the number of ignored files due to syntax issues in 'ignored_files.txt'
    with open("results/ignored_files.txt", "w") as f:
        f.write(f"Number of ignored files due to syntax issues: {ignored_files}\n")

    # Save the list of files with different extensions in 'other_extensions.txt'
    with open("results/other_extensions.txt", "w") as f:
        f.write("Files with different extensions:\n")
        for file in other_extensions:
            f.write(f"  {file}\n")


