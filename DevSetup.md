For development, run the following commands from the top level:

    mkdir lib
    pip install -t lib -r pip_deps.txt

Copy the API key for Blizzard's API into the api-auth.json file as the "blizzard" entry.

Create a service user account in the GAE console.  Copy the email address for
the service user into the api-auth.json file as the "oauth_client_email" entry.

Download the p12 key for the service user from the GAE console and convert it
into a pem file, using the following command.  The default password for the key
is 'notasecret'.

    openssl pkcs12 -in <p12 filename> -nodes -nocerts > oauth_private_key.pem

Put the pem file in the root directory of the ctrprogress project.  The pem
filename is required to be what is in the command above, and is already in
.gitignore to avoid committing it.

Run the following command to avoid committing secret data to git:

    git update-index --assume-unchanged api-auth.json
