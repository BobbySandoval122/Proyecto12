
package mx.orvia.campo

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.Uri
import android.os.Bundle

import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels

import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext

import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider

import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning

import mx.orvia.campo.ui.OrviaRoot
import mx.orvia.campo.ui.OrviaTheme

import java.io.File

class MainActivity : ComponentActivity() {

    private val model: OrviaViewModel by viewModels()

    private val connectivity by lazy {
        getSystemService(ConnectivityManager::class.java)
    }

    private val networkCallback =
        object : ConnectivityManager.NetworkCallback() {

            override fun onAvailable(network: Network) {
                runOnUiThread {
                    model.syncQueue()
                }
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {

            OrviaTheme {

                val context = LocalContext.current

                var cameraUri by remember {
                    mutableStateOf<Uri?>(null)
                }

                // Seleccionar imagen desde galeria
                val photoPicker =
                    rememberLauncherForActivityResult(
                        ActivityResultContracts.GetContent()
                    ) { uri ->

                        uri?.let {
                            model.selectPhoto(it)
                        }
                    }

                // Capturar fotografia con camara
                val photoCamera =
                    rememberLauncherForActivityResult(
                        ActivityResultContracts.TakePicture()
                    ) { success ->

                        if (success) {
                            cameraUri?.let {
                                model.selectPhoto(it)
                            }
                        }
                    }

                // Solicitar permisos de ubicacion
                val locationRequester =
                    rememberLauncherForActivityResult(
                        ActivityResultContracts.RequestMultiplePermissions()
                    ) { grants ->

                        if (grants.values.any { it }) {
                            findLocation()
                        }
                    }

                // Interfaz principal de Orvia
                OrviaRoot(
                    model = model,

                    onCamera = {

                        val file = File.createTempFile(
                            "captura_orvia_",
                            ".jpg",
                            context.cacheDir
                        )

                        // Usa el package real de la aplicacion
                        val uri = FileProvider.getUriForFile(
                            context,
                            "${context.packageName}.provider",
                            file
                        )

                        cameraUri = uri
                        photoCamera.launch(uri)
                    },

                    onGallery = {
                        photoPicker.launch("image/*")
                    },

                    onScan = {

                        GmsBarcodeScanning.getClient(this)
                            .startScan()
                            .addOnSuccessListener { item ->

                                item.rawValue?.let {
                                    model.scanResult(it)
                                }
                            }
                            .addOnFailureListener { error ->

                                model.scanResult(
                                    "Escaneo no disponible: ${error.message}"
                                )
                            }
                    },

                    onLocation = {

                        val fine = ContextCompat.checkSelfPermission(
                            this,
                            Manifest.permission.ACCESS_FINE_LOCATION
                        )

                        val coarse = ContextCompat.checkSelfPermission(
                            this,
                            Manifest.permission.ACCESS_COARSE_LOCATION
                        )

                        if (
                            fine == PackageManager.PERMISSION_GRANTED ||
                            coarse == PackageManager.PERMISSION_GRANTED
                        ) {
                            findLocation()
                        } else {

                            locationRequester.launch(
                                arrayOf(
                                    Manifest.permission.ACCESS_FINE_LOCATION,
                                    Manifest.permission.ACCESS_COARSE_LOCATION
                                )
                            )
                        }
                    }
                )
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun findLocation() {

        val locationClient =
            LocationServices.getFusedLocationProviderClient(this)

        locationClient.getCurrentLocation(
            Priority.PRIORITY_HIGH_ACCURACY,
            CancellationTokenSource().token
        ).addOnSuccessListener { location ->

            if (location != null) {
                model.setLocation(
                    location.latitude,
                    location.longitude
                )
            }
        }
    }

    override fun onStart() {
        super.onStart()

        try {
            connectivity.registerDefaultNetworkCallback(
                networkCallback
            )
        } catch (_: Exception) {
            // La app sigue funcionando sin este callback
        }
    }

    override fun onStop() {

        try {
            connectivity.unregisterNetworkCallback(
                networkCallback
            )
        } catch (_: Exception) {
            // Evitar fallo si no estaba registrado
        }

        super.onStop()
    }
}
