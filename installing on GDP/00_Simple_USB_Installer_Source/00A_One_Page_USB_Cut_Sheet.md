# GDP Training Academy USB install

**Before you start:** Proxmox VE 9 must already be installed on a dedicated, empty server. Use a 32 GB or larger **exFAT** USB drive labelled **ACADEMY** by default. If you use another label, keep it and replace `ACADEMY` in the mount path with the exact label from `lsblk -f`. Copy the entire **GDP Installer** folder onto it. FAT32 cannot hold the package files.

1. **Connect the USB drive.** On another computer, open the new server's Proxmox web interface. Select the server node, open **Shell**, and sign in as root.

2. **Paste this block into the Proxmox shell:**

   ```sh
   mkdir -p /mnt/academy
   mount -t exfat -o ro /dev/disk/by-label/ACADEMY /mnt/academy
   bash '/mnt/academy/GDP Installer/INSTALL.sh'
   ```

3. **Answer the installer.** Enter the website name you will use on your LAN, such as `academy.training.internal`. Enter a name only: no `https://`, IP address, or `.local` suffix. Review the detected network and storage, then type **yes**. The Academy VM sizes are set automatically. Leave the USB connected until completion.

4. **Check the finish message.** A successful run prints **Academy installation complete** and a receipt. If you close the shell, run the last command from step 2 again to see progress. You can also run:

   ```sh
   cat /root/academy-install/state /root/academy-install/receipt.txt
   ```

5. **Make the website reachable.** On the LAN DNS server or router used by learner computers, add an **A record** from your website name to the Proxmox LAN IP in the receipt. The installer cannot change your router or DNS server.

6. **Trust the site certificate on each Ubuntu PC.** Compare the Proxmox SSH fingerprint; copy `academy-ca.crt` with `scp`; compare `sha256sum`; then run `sudo install -o root -g root -m 0644 academy-ca.crt /usr/local/share/ca-certificates/academy-ca.crt` and `sudo update-ca-certificates`. Restart the browser. The detailed `README.md` covers Firefox if it still warns. Never copy a `.key` file or bypass a certificate warning.

7. **Sign in and check the Academy.** In the Proxmox shell, run the following command. Read the username and password from its `out-data` field, then sign in at your website name. Change the administrator password, create learner accounts, and follow the acceptance record before admitting learners.

   ```sh
   qm guest exec 9000 -- /bin/cat /opt/training-academy/secrets/initial-admin.txt
   ```

After installation finishes, run `umount /mnt/academy` to safely unmount the USB. The package's `README.md` and `INSTALLATION-GUIDE.pdf` contain the full instructions and troubleshooting steps.
