print ('----------------------------------------------------------------------------------------------------\n')
import os, shutil, socket, getpass, sys, subprocess, importlib.util

print('Checking if all necessary libraries are installed:\n')
subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
cryptography_found = importlib.util.find_spec('cryptography') is not None	
PATH = os.path.dirname(os.path.abspath(__file__))

if cryptography_found:
	from cryptography.fernet import Fernet
	
	print ('\n----------------------------------------------------------------------------------------------------\n')
	print ("Starting to run Arduino-CLI ('load-config-arduino-sensthread1.py')\n")
	print ('----------------------------------------------------------------------------------------------------\n')
	if os.path.exists(os.path.dirname(os.path.dirname(PATH))+'/arduino-cli/libraries'):
		print ('List of Arduino boards connected to the computer:')
		os.system('arduino-cli board list')
		print ('\n----------------------------------------------------------------------------------------------------\n')
		print ('Sketch generation and code import:')
		print ('Sensor: sensthread (Yun: 5.6.7.8)')
		os.system('arduino-cli sketch new '+PATH+'/arduino')
		shutil.copy2(PATH+'/sensthread1.ino', PATH+'/arduino/arduino.ino')
		configuration_loaded = False
		nodePath = PATH
		if nodePath.endswith('sensthread1'):
			nodePath = os.path.dirname(nodePath)
		def replace_line(file_name, line_num, text):
		    lines = open(file_name, 'r').readlines()
		    lines[line_num] = text
		    out = open(file_name, 'w')
		    out.writelines(lines)
		    out.close()
		with open(PATH+'/arduino/arduino.ino', 'r') as file:
		    lines = [line.rstrip() for line in file]
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.connect(("8.8.8.8", 80))
		ip = s.getsockname()[0]
		s.close()
		count = 0    
		for line in lines:
		    if (line.find('IPv4_WiFi_PC') != -1):
		        #ip = input("Enter the IP address of device '"+line[18:line.find('IPv4_WiFi_PC')-2]+"': ")
		        replace_line(PATH+'/arduino/arduino.ino', count, line[0:line.find('IPv4_WiFi_PC')]+ip+'"\n')
		    count += 1
		count = 0    
		for line in lines:
		    if (line.find('Mosquitto_PORT') != -1):
		        fog_name = line.split(' ')[1][5:999]
		        port = 1884
		        with open(nodePath+'/DeployV2/mosquitto-'+fog_name+'.conf', 'r') as file:
			        port = [line.rstrip() for line in file][1][9:999]
		        replace_line(PATH+'/arduino/arduino.ino', count, line[0:line.find('Mosquitto_PORT')]+port+'"\n')
		    count += 1
		print ('\n----------------------------------------------------------------------------------------------------')
		print()
		if os.path.exists(nodePath+'/foga0/credentials-foga0.txt') and os.path.exists(nodePath+'/foga0/key-foga0.key'):
			with open(nodePath+'/foga0/key-foga0.key', 'rb') as file:
				key = file.read()
			with open(nodePath+'/foga0/credentials-foga0.txt', 'rb') as encrypted_file:
				encrypted_credentials = encrypted_file.read()
			decrypted_credentials = fernet = Fernet(key).decrypt(encrypted_credentials)
			print("Does your 'foga' device have a password? (yes/no): "+decrypted_credentials.decode().split('\n')[0])
			if decrypted_credentials.decode().split('\n')[0] == 'yes':
				print("Enter the username of device 'foga': "+decrypted_credentials.decode().split('\n')[1])
				username = decrypted_credentials.decode().split('\n')[1]
				print("Enter the password of device 'foga': ")
				password = decrypted_credentials.decode().split('\n')[2]
			count = 0
			if decrypted_credentials.decode().split('\n')[0] == 'yes':
			    with open(PATH+'/arduino/arduino.ino', 'r') as file:
			        lines = [line.rstrip() for line in file]
			    for line in lines:
			        if (line.find('_foga")') != -1):
			            replace_line(PATH+'/arduino/arduino.ino', count, line[0:line.find('_foga")')+len('_foga")')-1]+', "'+username+'", "'+password+'"'+line[line.find('_foga")')+len('_foga")')-1:999]+'\n')
			        count += 1
			configuration_loaded = True
		else:
			print("You must load the raspberry configuration ('load-swarm-worker-foga0.py') first")
			configuration_loaded = False
		
		if configuration_loaded:
			print ('\n----------------------------------------------------------------------------------------------------')
			print ("\nCompiling the sketch and loading it on the Arduino 'sensthread' (Yun: 5.6.7.8)")
			if "Yun"=="AdafruitCircuitPlayground": modelo="arduino:avr:circuitplay32u4cat"
			elif "Yun"=="BT": modelo="arduino:avr:bt"
			elif "Yun"=="DuemilanoveOrDiecimila": modelo="arduino:avr:diecimila"
			elif "Yun"=="Esplora": modelo="arduino:avr:esplora"
			elif "Yun"=="Ethernet": modelo="arduino:avr:ethernet"
			elif "Yun"=="Fio": modelo="arduino:avr:fio"
			elif "Yun"=="Gemma": modelo="arduino:avr:gemma"
			elif "Yun"=="Industrial101": modelo="arduino:avr:chiwawa"
			elif "Yun"=="Leonardo": modelo="arduino:avr:leonardo"
			elif "Yun"=="LeonardoETH": modelo="arduino:avr:leonardoeth"
			elif "Yun"=="MegaADK": modelo="arduino:avr:megaADK"
			elif "Yun"=="MegaOrMega2560": modelo="arduino:avr:mega"
			elif "Yun"=="Micro": modelo="arduino:avr:micro"
			elif "Yun"=="Mini": modelo="arduino:avr:mini"
			elif "Yun"=="NGOrOlder": modelo="arduino:avr:atmegang"
			elif "Yun"=="Nano": modelo="arduino:avr:nano"
			elif "Yun"=="ProOrPro Mini": modelo="arduino:avr:pro"
			elif "Yun"=="RobotControl": modelo="arduino:avr:robotControl"
			elif "Yun"=="RobotMotor": modelo="arduino:avr:robotMotor"
			elif "Yun"=="Uno": modelo="arduino:avr:uno"
			elif "Yun"=="UnoMini": modelo="arduino:avr:unomini"
			elif "Yun"=="UnoWiFi": modelo="arduino:avr:unowifi"
			elif "Yun"=="Yun": modelo="arduino:avr:yun"
			elif "Yun"=="YunMini": modelo="arduino:avr:yunmini"
			elif "Yun"=="LilyPadArduino": modelo="arduino:avr:lilypad"
			elif "Yun"=="LilyPadArduinoUSB": modelo="arduino:avr:LilyPadUSB"
			elif "Yun"=="LininoOne": modelo="arduino:avr:one"
			elif "Yun"=="LolinWemosD1Mini": modelo="esp8266:esp8266:d1_mini"
			os.system('arduino-cli compile '+PATH+'/arduino/arduino.ino --fqbn '+modelo)
			os.system('arduino-cli upload '+PATH+'/arduino/arduino.ino --port 5.6.7.8 --fqbn '+modelo)
		print ('\n----------------------------------------------------------------------------------------------------\n')
		shutil.rmtree(PATH+'/arduino')
		print ("End of Arduino-CLI run ('load-config-arduino-sensthread1.py')")
	else:
		print("Arduino Command Line is not installed. Please, run the installer script ('install-arduino.py')")
else:
	print ("\nThe required libraries are not installed. Please, rerun the script again ('load-config-arduino-sensthread1.py')")
print ('\n----------------------------------------------------------------------------------------------------\n')
getpass.getpass("Press 'Enter' to continue... ")
print ('\n----------------------------------------------------------------------------------------------------')
