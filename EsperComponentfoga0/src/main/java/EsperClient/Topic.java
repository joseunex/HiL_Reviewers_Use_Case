package EsperClient;

public class Topic{
	String nombre;
	boolean suscribir;
	boolean publicar;
	
	public Topic(String nombre, boolean suscribir, boolean publicar) {
		super();
		this.nombre = nombre;
		this.suscribir = suscribir;
		this.publicar = publicar;
	}
	
	public String getNombre() {
		return nombre;
	}
	
	public void setNombre(String nombre) {
		this.nombre = nombre;
	}
	
	public boolean isSuscribir() {
		return suscribir;
	}
	
	public void setSuscribir(boolean suscribir) {
		this.suscribir = suscribir;
	}
	
	public boolean isPublicar() {
		return publicar;
	}
	
	public void setPublicar(boolean publicar) {
		this.publicar = publicar;
	}
	
}
